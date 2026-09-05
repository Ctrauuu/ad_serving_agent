import json

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.milvus import milvus_client
from app.models import (
    AnomalyCause,
    AnomalyRecord,
    CaseLibrary,
    InterventionSuggestion,
)
from app.schemas import (
    InterventionSuggestionRead,
    SuggestionActionType,
    SuggestionCandidate,
    SuggestionGenerationOutput,
    SuggestionGenerationResult,
    SuggestionRiskLevel,
)
from app.services.embedding import embed_text
from app.services.goal import get_goal_llm


_HIGH_RISK_ACTIONS: frozenset[
    SuggestionActionType
] = frozenset(
    {
        "pause",
        "adjust_budget",
        "adjust_bid",
        "switch_channel",
    }
)

_MEDIUM_RISK_ACTIONS: frozenset[
    SuggestionActionType
] = frozenset(
    {
        "replace_creative",
        "narrow_audience",
    }
)

_CONSERVATIVE_ACTIONS: frozenset[
    SuggestionActionType
] = frozenset(
    {
        "extend_observation",
        "manual_review",
    }
)

_CONFLICTING_ACTION_PAIRS = {
    frozenset({"pause", "adjust_budget"}),
    frozenset({"pause", "adjust_bid"}),
}

_suggestion_parser = PydanticOutputParser(
    pydantic_object=SuggestionGenerationOutput,
)

_SUGGESTION_SYSTEM_PROMPT = f"""
你负责根据广告投放异常、原因假设和历史案例，
生成可解释的干预建议。

规则：
1. 必须生成 2 至 5 条建议，并且只能有一条主建议。
2. action_type 只能使用：
   pause、adjust_budget、adjust_bid、
   replace_creative、narrow_audience、
   switch_channel、extend_observation、manual_review。
3. 每条建议的 cause_id 必须来自 valid_cause_ids。
4. 建议必须与对应原因一致，禁止脱离原因生成动作。
5. metric_evidence 只能使用输入中的真实指标和证据。
6. triggered_rule 必须说明触发建议的异常规则或原因。
7. expected_impact 必须描述预期影响，不得捏造无依据的精确结果。
8. action_params 只填写动作参数，不得生成 campaign_id、
   anomaly_id、ad_group_id 或其他目标编号。
9. 不得同时建议暂停和调预算，也不得同时建议暂停和调出价。
10. data_sufficient 为 false 时，主建议必须是
    extend_observation 或 manual_review。
11. 历史案例为空时，只基于当前异常和原因生成，
    不得虚构历史案例。
12. 历史案例只能作为参考，不能替代当前指标证据。
13. 必须输出合法 JSON。

{_suggestion_parser.get_format_instructions()}
"""


def format_intervention_case(
    case: CaseLibrary,
) -> str:
    """把历史干预案例转换为稳定的语义文本。

    Args:
        case: MySQL case_library 中的历史干预案例。

    Returns:
        包含异常场景、原因、动作和结果的文本，
        用于生成 document 类型的 Embedding。
    """
    payload = {
        "anomaly_type": case.anomaly_type,
        "scene": case.scene_desc,
        "cause": case.cause,
        "action": case.action,
        "effectiveness": case.effectiveness,
        "conclusion": case.conclusion,
    }

    return (
        "历史投放干预案例：\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    )


def format_suggestion_scene(
    anomaly: AnomalyRecord,
    causes: list[AnomalyCause],
) -> str:
    """把当前异常和原因假设转换为检索文本。

    Args:
        anomaly: 当前需要生成干预建议的异常记录。
        causes: 当前异常已经生成的原因假设列表。

    Returns:
        用于生成 query 类型 Embedding 的稳定文本。
    """
    sorted_causes = sorted(
        causes,
        key=lambda cause: (
            -float(cause.confidence),
            cause.id,
        ),
    )

    payload = {
        "anomaly": {
            "anomaly_type": anomaly.anomaly_type,
            "metric": anomaly.metric,
            "metric_value": anomaly.metric_value,
            "baseline_value": anomaly.baseline_value,
            "severity": anomaly.severity,
            "evidence": anomaly.evidence_json,
        },
        "causes": [
            {
                "cause_type": cause.cause_type,
                "hypothesis": cause.hypothesis,
                "confidence": cause.confidence,
                "evidence_sources": (
                    cause.evidence_sources
                ),
                "data_sufficient": (
                    cause.data_sufficient
                ),
            }
            for cause in sorted_causes
        ],
    }

    return (
        "当前待干预的投放异常：\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    )


async def retrieve_similar_intervention_cases(
    session: AsyncSession,
    scene_text: str,
    limit: int = 5,
) -> list[dict[str, object]]:
    """召回并读取相似的历史干预案例。

    Args:
        session: 数据库异步会话。
        scene_text: 当前异常和原因组成的检索文本。
        limit: 最多召回的历史案例数量。

    Returns:
        按 Milvus 相似度从高到低排列的完整案例列表。

    Raises:
        ValueError: 检索文本为空。
        RuntimeError: Embedding 或 Milvus 调用失败。
    """
    query_vector = await embed_text(
        scene_text,
        text_type="query",
    )
    matches = (
        await milvus_client
        .search_similar_intervention_cases(
            intervention_vector=query_vector,
            limit=limit,
        )
    )

    if not matches:
        return []

    case_ids = [
        int(match["case_id"])
        for match in matches
    ]

    cases = list(
        (
            await session.scalars(
                select(CaseLibrary).where(
                    CaseLibrary.id.in_(case_ids),
                    CaseLibrary.case_type
                    == "intervention",
                )
            )
        ).all()
    )
    cases_by_id = {
        case.id: case
        for case in cases
    }

    return [
        {
            "ref": f"intervention_case:{case_id}",
            "case_id": case_id,
            "score": float(match["score"]),
            "anomaly_type": (
                cases_by_id[case_id].anomaly_type
            ),
            "scene_desc": (
                cases_by_id[case_id].scene_desc
            ),
            "cause": cases_by_id[case_id].cause,
            "action": cases_by_id[case_id].action,
            "effectiveness": (
                cases_by_id[case_id].effectiveness
            ),
            "conclusion": (
                cases_by_id[case_id].conclusion
            ),
        }
        for match in matches
        if (
            case_id := int(match["case_id"])
        ) in cases_by_id
    ]


def grade_suggestion_risk(
    action_type: SuggestionActionType,
) -> SuggestionRiskLevel:
    """根据干预动作类型确定风险等级。

    Args:
        action_type: 经过 Schema 校验的干预动作类型。

    Returns:
        服务端计算出的低、中或高风险等级。
    """
    if action_type in _HIGH_RISK_ACTIONS:
        return "高"

    if action_type in _MEDIUM_RISK_ACTIONS:
        return "中"

    return "低"


def validate_conservative_primary(
    suggestions: list[SuggestionCandidate],
    data_sufficient: bool,
) -> None:
    """在数据不足时限制主建议为保守动作。

    Args:
        suggestions: 大模型生成并通过 Schema 校验的建议。
        data_sufficient: 销售反馈等归因数据是否充分。

    Returns:
        无返回值。

    Raises:
        ValueError: 缺少主建议，或者数据不足时主建议
            不是延长观察或人工复核。
    """
    primary = next(
        (
            suggestion
            for suggestion in suggestions
            if suggestion.is_primary
        ),
        None,
    )

    if primary is None:
        raise ValueError("建议结果缺少主建议")

    if (
        not data_sufficient
        and primary.action_type
        not in _CONSERVATIVE_ACTIONS
    ):
        raise ValueError(
            "归因数据不足时，主建议必须为"
            "延长观察或人工复核"
        )


def filter_conflicting_suggestions(
    suggestions: list[SuggestionCandidate],
) -> list[SuggestionCandidate]:
    """过滤重复动作和互相冲突的候选建议。

    Args:
        suggestions: 大模型生成并通过 Schema 校验的建议列表。

    Returns:
        主建议优先、动作不重复且不存在冲突的建议列表。

    Raises:
        ValueError: 过滤后不足两条建议，无法满足
            主建议加备选建议的要求。
    """
    ordered = sorted(
        enumerate(suggestions),
        key=lambda item: (
            not item[1].is_primary,
            item[0],
        ),
    )

    accepted: list[SuggestionCandidate] = []
    accepted_actions: set[SuggestionActionType] = set()

    for _, suggestion in ordered:
        action = suggestion.action_type

        if action in accepted_actions:
            continue

        has_conflict = any(
            frozenset({action, existing_action})
            in _CONFLICTING_ACTION_PAIRS
            for existing_action in accepted_actions
        )

        if has_conflict:
            continue

        accepted.append(suggestion)
        accepted_actions.add(action)

    if len(accepted) < 2:
        raise ValueError(
            "建议去重后至少需要一条主建议和一条备选建议"
        )

    return accepted


async def generate_suggestion_candidates(
    anomaly: AnomalyRecord,
    causes: list[AnomalyCause],
    cases: list[dict[str, object]],
    data_sufficient: bool,
) -> list[SuggestionCandidate]:
    """调用大模型生成并校验候选干预建议。

    Args:
        anomaly: 当前需要生成建议的异常记录。
        causes: 当前异常对应的原因假设。
        cases: Milvus 召回并从 MySQL 补齐的历史案例。
        data_sufficient: 归因所需业务数据是否充分。

    Returns:
        已校验、去重且不存在动作冲突的建议列表。

    Raises:
        ValueError: 模型输出格式错误、引用不存在的原因、
            建议发生冲突或数据不足时主建议不保守。
    """
    valid_cause_ids = {
        cause.id
        for cause in causes
    }

    input_data = {
        "data_sufficient": data_sufficient,
        "valid_cause_ids": sorted(
            valid_cause_ids
        ),
        "historical_case_notice": (
            None
            if cases
            else "无历史干预案例参考"
        ),
        "current_scene": (
            format_suggestion_scene(
                anomaly,
                causes,
            )
        ),
        "historical_cases": cases,
    }

    response = await get_goal_llm().ainvoke(
        [
            SystemMessage(
                content=_SUGGESTION_SYSTEM_PROMPT
            ),
            HumanMessage(
                content=json.dumps(
                    input_data,
                    ensure_ascii=False,
                    default=str,
                )
            ),
        ]
    )

    if not isinstance(response.content, str):
        raise ValueError("模型未返回文本内容")

    try:
        result = _suggestion_parser.parse(
            response.content
        )
    except OutputParserException as exc:
        raise ValueError(
            "模型返回内容不符合干预建议结构"
        ) from exc

    for suggestion in result.suggestions:
        if suggestion.cause_id not in valid_cause_ids:
            raise ValueError(
                "模型引用了不存在的原因："
                f"{suggestion.cause_id}"
            )

    filtered = filter_conflicting_suggestions(
        result.suggestions
    )
    validate_conservative_primary(
        filtered,
        data_sufficient,
    )

    return filtered


async def get_suggestion_generation_context(
    session: AsyncSession,
    anomaly_id: int,
) -> tuple[
    AnomalyRecord,
    list[AnomalyCause],
    bool,
] | None:
    """读取并校验干预建议生成所需的数据。

    Args:
        session: 数据库异步会话。
        anomaly_id: 需要生成干预建议的异常编号。

    Returns:
        异常记录、按置信度排序的原因列表及
        数据充分性；异常不存在时返回 None。

    Raises:
        ValueError: 异常尚未归因、目标类型不支持、
            原因不存在，或已有建议进入审批执行流程。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        return None

    if anomaly.status != "已归因":
        raise ValueError(
            "异常尚未完成原因归因"
        )

    if anomaly.target_type != "ad_group":
        raise ValueError(
            "暂不支持该异常目标类型生成干预建议"
        )

    causes = list(
        (
            await session.scalars(
                select(AnomalyCause)
                .where(
                    AnomalyCause.anomaly_id
                    == anomaly.id
                )
                .order_by(
                    AnomalyCause.confidence.desc(),
                    AnomalyCause.id,
                )
            )
        ).all()
    )

    if not causes:
        raise ValueError(
            "异常原因不存在，请先执行原因归因"
        )

    existing_statuses = list(
        (
            await session.scalars(
                select(
                    InterventionSuggestion.status
                ).where(
                    InterventionSuggestion.anomaly_id
                    == anomaly.id
                )
            )
        ).all()
    )

    if any(
        status != "待提交"
        for status in existing_statuses
    ):
        raise ValueError(
            "已有建议进入审批或执行流程，"
            "不允许重新生成"
        )

    data_sufficient = all(
        cause.data_sufficient
        for cause in causes
    )

    return anomaly, causes, data_sufficient


async def save_generated_suggestions(
    session: AsyncSession,
    anomaly: AnomalyRecord,
    candidates: list[SuggestionCandidate],
    data_sufficient: bool,
    has_historical_cases: bool,
) -> list[InterventionSuggestion]:
    """替换待提交建议并保存新的干预建议。

    Args:
        session: 数据库异步会话。
        anomaly: 建议对应的异常记录。
        candidates: 已完成原因、冲突和安全校验的候选建议。
        data_sufficient: 归因数据是否充分。
        has_historical_cases: 是否召回到历史干预案例。

    Returns:
        已加入当前事务并获得主键的建议记录列表。

    Raises:
        ValueError: 异常目标不是广告组。
    """
    if anomaly.target_type != "ad_group":
        raise ValueError(
            "暂不支持该异常目标类型保存干预建议"
        )

    await session.execute(
        delete(InterventionSuggestion).where(
            InterventionSuggestion.anomaly_id
            == anomaly.id,
            InterventionSuggestion.status
            == "待提交",
        )
    )

    reserved_param_keys = {
        "campaign_id",
        "anomaly_id",
        "target_id",
        "ad_group_id",
    }
    rule_name = (
        anomaly.evidence_json or {}
    ).get("rule_name")

    records: list[InterventionSuggestion] = []

    for candidate in candidates:
        candidate_data = candidate.model_dump(
            mode="json"
        )
        action_params = {
            key: value
            for key, value
            in candidate_data["action_params"].items()
            if key not in reserved_param_keys
        }
        action_params["ad_group_id"] = (
            anomaly.target_id
        )

        metric_evidence = {
            "metric": anomaly.metric,
            "metric_value": (
                str(anomaly.metric_value)
                if anomaly.metric_value is not None
                else None
            ),
            "baseline_value": (
                str(anomaly.baseline_value)
                if anomaly.baseline_value is not None
                else None
            ),
            "anomaly_evidence": (
                anomaly.evidence_json
            ),
            "suggestion_evidence": (
                candidate_data["metric_evidence"]
            ),
            "data_sufficient": data_sufficient,
            "historical_case_notice": (
                None
                if has_historical_cases
                else "无历史干预案例参考"
            ),
        }

        record = InterventionSuggestion(
            anomaly_id=anomaly.id,
            campaign_id=anomaly.campaign_id,
            target_type=anomaly.target_type,
            target_id=anomaly.target_id,
            cause_id=candidate.cause_id,
            action_type=candidate.action_type,
            action_params=action_params,
            metric_evidence=metric_evidence,
            triggered_rule=(
                str(rule_name)
                if rule_name
                else candidate.triggered_rule
            ),
            expected_impact=(
                candidate_data["expected_impact"]
            ),
            risk_notes=candidate.risk_notes,
            risk_level=grade_suggestion_risk(
                candidate.action_type
            ),
            is_primary=candidate.is_primary,
            status="待提交",
        )
        records.append(record)

    session.add_all(records)
    await session.flush()

    return records


async def generate_intervention_suggestions(
    session: AsyncSession,
    anomaly_id: int,
) -> SuggestionGenerationResult | None:
    """召回历史案例并生成、保存干预建议。

    Args:
        session: 数据库异步会话。
        anomaly_id: 需要生成干预建议的异常编号。

    Returns:
        包含主建议、备选建议和召回状态的结果；
        异常不存在时返回 None。

    Raises:
        ValueError: 异常状态、原因、模型结果或
            建议安全策略不符合要求。
        RuntimeError: Embedding、Milvus 或模型调用失败。
    """
    context = await get_suggestion_generation_context(
        session,
        anomaly_id,
    )

    if context is None:
        return None

    anomaly, causes, data_sufficient = context

    try:
        scene_text = format_suggestion_scene(
            anomaly,
            causes,
        )
        cases = (
            await retrieve_similar_intervention_cases(
                session,
                scene_text,
            )
        )
        candidates = (
            await generate_suggestion_candidates(
                anomaly=anomaly,
                causes=causes,
                cases=cases,
                data_sufficient=data_sufficient,
            )
        )
        records = await save_generated_suggestions(
            session=session,
            anomaly=anomaly,
            candidates=candidates,
            data_sufficient=data_sufficient,
            has_historical_cases=bool(cases),
        )

        await session.commit()

        for record in records:
            await session.refresh(record)

    except Exception:
        await session.rollback()
        raise

    return SuggestionGenerationResult(
        anomaly_id=anomaly.id,
        data_sufficient=data_sufficient,
        has_historical_cases=bool(cases),
        suggestions=[
            InterventionSuggestionRead.model_validate(
                record
            )
            for record in records
        ],
    )


async def get_intervention_suggestion_result(
    session: AsyncSession,
    anomaly_id: int,
) -> SuggestionGenerationResult | None:
    """查询异常已经保存的干预建议。

    Args:
        session: 数据库异步会话。
        anomaly_id: 需要查询建议的异常编号。

    Returns:
        已保存的建议、数据充分性和案例召回状态；
        异常或建议不存在时返回 None。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        return None

    records = list(
        (
            await session.scalars(
                select(InterventionSuggestion)
                .where(
                    InterventionSuggestion.anomaly_id
                    == anomaly.id
                )
                .order_by(
                    InterventionSuggestion.is_primary.desc(),
                    InterventionSuggestion.id,
                )
            )
        ).all()
    )

    if not records:
        return None

    metadata = records[0].metric_evidence or {}

    data_sufficient = bool(
        metadata.get(
            "data_sufficient",
            False,
        )
    )
    has_historical_cases = (
        "historical_case_notice" in metadata
        and metadata["historical_case_notice"] is None
    )

    return SuggestionGenerationResult(
        anomaly_id=anomaly.id,
        data_sufficient=data_sufficient,
        has_historical_cases=has_historical_cases,
        suggestions=[
            InterventionSuggestionRead.model_validate(
                record
            )
            for record in records
        ],
    )