import json
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.milvus import milvus_client
from app.models import (
    AdGroup,
    AdMetricRealtime,
    AdPlan,
    AnomalyCause,
    AnomalyRecord,
    Audience,
    CaseLibrary,
    Channel,
    Creative,
    SalesFeedback,
)
from app.schemas import (
    AnomalyCauseRead,
    CauseAnalysisOutput,
    CauseAnalysisResult,
    CauseHypothesis,
)
from app.services.embedding import embed_text
from app.services.goal import get_goal_llm


_SALES_FEEDBACK_MIN_COUNT = 3
_SALES_FEEDBACK_FRESH_HOURS = 24
_cause_parser = PydanticOutputParser(
    pydantic_object=CauseAnalysisOutput,
)

_CAUSE_SYSTEM_PROMPT = f"""
你负责分析广告投放异常，并生成多个原因假设。

规则：
1. 必须生成 2 至 5 个不同的原因假设。
2. 原因按 confidence 从高到低排列。
3. 只能引用输入中真实存在的 ref，禁止编造证据。
4. 历史案例只能作为参考，不能当成当前异常的事实。
5. 没有历史案例时，仅根据当前业务信号分析。
6. 销售反馈不足时，应降低结论确定性。
7. 每个原因至少引用一条指标或业务证据。
8. 只解释可能原因，不得输出暂停、调预算等动作建议。
9. 必须输出合法 JSON。
10. evidence_sources 中每个 ref 和 type 必须与
allowed_evidence_catalog 中的键和值完全一致。

{_cause_parser.get_format_instructions()}
"""


async def collect_attribution_signals(
    session: AsyncSession,
    anomaly: AnomalyRecord,
) -> tuple[dict[str, Any], bool]:
    """收集异常归因所需的业务和指标信号。

    Args:
        session: 数据库异步会话。
        anomaly: 待归因的异常记录。

    Returns:
        信号字典，以及销售反馈数据是否充分。

    Raises:
        ValueError: 异常目标不受支持，或关联广告组不存在。
    """
    if anomaly.target_type != "ad_group":
        raise ValueError(
            f"暂不支持目标类型：{anomaly.target_type}"
        )

    group = await session.get(
        AdGroup,
        anomaly.target_id,
    )

    if (
        group is None
        or group.campaign_id != anomaly.campaign_id
    ):
        raise ValueError("异常关联的广告组不存在")

    plan = await session.get(
        AdPlan,
        group.ad_plan_id,
    )
    channel = (
        await session.get(Channel, plan.channel_id)
        if plan is not None
        else None
    )
    audience = (
        await session.get(Audience, group.audience_id)
        if group.audience_id is not None
        else None
    )
    creative = (
        await session.get(Creative, group.creative_id)
        if group.creative_id is not None
        else None
    )

    metric = await session.scalar(
        select(AdMetricRealtime)
        .where(
            AdMetricRealtime.campaign_id
            == anomaly.campaign_id,
            AdMetricRealtime.dimension
            == "ad_group",
            AdMetricRealtime.dim_id
            == group.id,
            AdMetricRealtime.time_window
            == "hour",
            AdMetricRealtime.collected_at
            <= anomaly.detected_at
            + timedelta(minutes=10),
        )
        .order_by(
            AdMetricRealtime.collected_at.desc()
        )
    )

    feedbacks = list(
        (
            await session.scalars(
                select(SalesFeedback)
                .where(
                    SalesFeedback.campaign_id
                    == anomaly.campaign_id,
                    or_(
                        SalesFeedback.ad_group_id
                        == group.id,
                        SalesFeedback.ad_group_id.is_(
                            None
                        ),
                    ),
                )
                .order_by(
                    SalesFeedback.feedback_at.desc()
                )
            )
        ).all()
    )

    feedback_cutoff = (
        anomaly.detected_at
        - timedelta(
            hours=_SALES_FEEDBACK_FRESH_HOURS
        )
    )
    recent_feedbacks = [
        item
        for item in feedbacks
        if item.feedback_at >= feedback_cutoff
    ]
    data_sufficient = (
        len(recent_feedbacks)
        >= _SALES_FEEDBACK_MIN_COUNT
    )

    quality_distribution = dict(
        Counter(
            item.lead_quality
            for item in feedbacks
        )
    )
    invalid_reasons = dict(
        Counter(
            item.invalid_reason
            for item in feedbacks
            if item.invalid_reason
        )
    )
    profile_values = [
        item.customer_profile_match
        for item in feedbacks
        if item.customer_profile_match is not None
    ]
    profile_match_rate = (
        sum(profile_values) / len(profile_values)
        if profile_values
        else None
    )
    deal_cycles = [
        item.deal_cycle_days
        for item in feedbacks
        if item.deal_cycle_days is not None
    ]
    average_deal_cycle = (
        sum(deal_cycles) / len(deal_cycles)
        if deal_cycles
        else None
    )

    signals: dict[str, Any] = {
        "anomaly": {
            "ref": f"anomaly:{anomaly.id}",
            "anomaly_type": anomaly.anomaly_type,
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
            "severity": anomaly.severity,
            "detected_at": (
                anomaly.detected_at.isoformat()
            ),
            "rule_evidence": anomaly.evidence_json,
        },
        "ad_group": {
            "ref": f"ad_group:{group.id}",
            "name": group.name,
            "bid": str(group.bid),
            "budget_daily": str(
                group.budget_daily
            ),
            "status": group.status,
        },
        "channel": (
            {
                "ref": f"channel:{channel.id}",
                "name": channel.name,
                "platform": channel.platform,
                "rules": channel.rules,
            }
            if channel is not None
            else None
        ),
        "audience": (
            {
                "ref": f"audience:{audience.id}",
                "name": audience.name,
                "targeting_desc": (
                    audience.targeting_desc
                ),
                "audience_type": (
                    audience.audience_type
                ),
                "estimated_size": (
                    audience.estimated_size
                ),
            }
            if audience is not None
            else None
        ),
        "creative": (
            {
                "ref": f"creative:{creative.id}",
                "name": creative.name,
                "type": creative.type,
                "selling_point_tags": (
                    creative.selling_point_tags
                ),
                "version": creative.version,
                "status": creative.status,
                "running_days": max(
                    (
                        anomaly.detected_at
                        - creative.created_at
                    ).days,
                    0,
                ),
            }
            if creative is not None
            else None
        ),
        "landing_page": (
            {
                "ref": (
                    f"landing_page:creative:"
                    f"{creative.id}"
                ),
                "url": creative.landing_page_url,
            }
            if (
                creative is not None
                and creative.landing_page_url
            )
            else None
        ),
        "metric_snapshot": (
            {
                "ref": (
                    f"metric:ad_group:{group.id}:"
                    f"{metric.window_start.isoformat()}"
                ),
                "impression": metric.impression,
                "click": metric.click,
                "cost": str(metric.cost),
                "lead": metric.lead,
                "valid_lead": metric.valid_lead,
                "order": metric.order,
                "ctr": (
                    str(metric.ctr)
                    if metric.ctr is not None
                    else None
                ),
                "cpc": (
                    str(metric.cpc)
                    if metric.cpc is not None
                    else None
                ),
                "cpa": (
                    str(metric.cpa)
                    if metric.cpa is not None
                    else None
                ),
                "roi": (
                    str(metric.roi)
                    if metric.roi is not None
                    else None
                ),
                "collected_at": (
                    metric.collected_at.isoformat()
                ),
            }
            if metric is not None
            else None
        ),
        "sales_feedback": {
            "ref": (
                f"sales_feedback:campaign:"
                f"{anomaly.campaign_id}:"
                f"ad_group:{group.id}"
            ),
            "total_count": len(feedbacks),
            "recent_count": len(recent_feedbacks),
            "latest_at": (
                feedbacks[0].feedback_at.isoformat()
                if feedbacks
                else None
            ),
            "quality_distribution": (
                quality_distribution
            ),
            "invalid_reasons": invalid_reasons,
            "profile_match_rate": (
                profile_match_rate
            ),
            "average_deal_cycle_days": (
                average_deal_cycle
            ),
            "data_sufficient": data_sufficient,
        },
    }

    return signals, data_sufficient


def format_anomaly_scene(
    signals: dict[str, Any],
) -> str:
    """把结构化归因信号转换为稳定的异常场景文本。

    Args:
        signals: 素材、人群、渠道、指标和销售反馈信号。

    Returns:
        可用于 Embedding 的异常场景文本。
    """
    return (
        "异常归因场景：\n"
        + json.dumps(
            signals,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    )


async def retrieve_similar_cases(
    session: AsyncSession,
    scene_text: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """召回当前异常的相似历史案例。

    Args:
        session: 数据库异步会话。
        scene_text: 当前异常的归因场景文本。
        limit: 最大召回案例数量。

    Returns:
        按向量相似度排序的完整历史案例列表。
    """
    query_vector = await embed_text(
        scene_text,
        text_type="query",
    )
    matches = (
        await milvus_client
        .search_similar_anomaly_cases(
            scene_vector=query_vector,
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
                    CaseLibrary.id.in_(case_ids)
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
            "ref": f"case:{case_id}",
            "case_id": case_id,
            "score": float(match["score"]),
            "anomaly_type": (
                cases_by_id[case_id].anomaly_type
            ),
            "scene_desc": (
                cases_by_id[case_id].scene_desc
            ),
            "cause": cases_by_id[case_id].cause,
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


def build_evidence_catalog(
    signals: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, str]:
    """建立允许大模型引用的证据目录。

    Args:
        signals: 当前异常的多维信号。
        cases: Milvus 召回的历史案例。

    Returns:
        证据 ref 到证据类型的映射。
    """
    signal_types = {
        "anomaly": "anomaly",
        "ad_group": "ad_group",
        "channel": "channel",
        "audience": "audience",
        "creative": "creative",
        "landing_page": "landing_page",
        "metric_snapshot": "metric_snapshot",
        "sales_feedback": "sales_feedback",
    }
    catalog: dict[str, str] = {}

    for name, evidence_type in signal_types.items():
        value = signals.get(name)

        if (
            isinstance(value, dict)
            and isinstance(value.get("ref"), str)
        ):
            catalog[value["ref"]] = evidence_type

    for case in cases:
        case_ref = case.get("ref")

        if isinstance(case_ref, str):
            catalog[case_ref] = "case"

    return catalog


async def generate_cause_hypotheses(
    signals: dict[str, Any],
    cases: list[dict[str, Any]],
    data_sufficient: bool,
) -> list[CauseHypothesis]:
    """调用大模型生成并校验多个原因假设。

    Args:
        signals: 当前异常的多维业务信号。
        cases: 召回的相似历史案例。
        data_sufficient: 销售反馈数据是否充分。

    Returns:
        按置信度从高到低排列的原因假设。

    Raises:
        ValueError: 模型内容不合法或引用虚假证据。
    """
    evidence_catalog = build_evidence_catalog(
        signals,
        cases,
    )
    input_data = {
        "data_sufficient": data_sufficient,
        "historical_case_notice": (
            None
            if cases
            else "无历史案例参考"
        ),
        "signals": signals,
        "historical_cases": cases,
        "allowed_evidence_catalog": evidence_catalog,
    }

    response = await get_goal_llm().ainvoke(
        [
            SystemMessage(
                content=_CAUSE_SYSTEM_PROMPT
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
        result = _cause_parser.parse(
            response.content
        )
    except OutputParserException as exc:
        raise ValueError(
            "模型返回内容不符合归因结构"
        ) from exc

    for cause in result.causes:
        for evidence in cause.evidence_sources:
            expected_type = evidence_catalog.get(
                evidence.ref
            )

            if expected_type is None:
                raise ValueError(
                    "模型引用了不存在的证据："
                    f"{evidence.ref}"
                )

            if expected_type != evidence.type:
                raise ValueError(
                    "模型证据类型不匹配："
                    f"{evidence.ref}"
                )

    return sorted(
        result.causes,
        key=lambda cause: cause.confidence,
        reverse=True,
    )


async def analyze_anomaly_cause(
    session: AsyncSession,
    anomaly_id: int,
) -> CauseAnalysisResult | None:
    """分析异常原因并替换已有原因假设。

    Args:
        session: 数据库异步会话。
        anomaly_id: 待归因异常编号。

    Returns:
        完整归因结果；异常不存在时返回 None。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        return None

    try:
        signals, data_sufficient = (
            await collect_attribution_signals(
                session,
                anomaly,
            )
        )
        scene_text = format_anomaly_scene(
            signals
        )
        cases = await retrieve_similar_cases(
            session,
            scene_text,
        )
        hypotheses = (
            await generate_cause_hypotheses(
                signals=signals,
                cases=cases,
                data_sufficient=data_sufficient,
            )
        )

        await session.execute(
            delete(AnomalyCause).where(
                AnomalyCause.anomaly_id
                == anomaly.id
            )
        )

        cause_records = [
            AnomalyCause(
                anomaly_id=anomaly.id,
                cause_type=item.cause_type,
                hypothesis=item.hypothesis,
                confidence=(
                    Decimal(
                        str(item.confidence)
                    ).quantize(
                        Decimal("0.001")
                    )
                ),
                evidence_sources=[
                    evidence.model_dump(
                        mode="json"
                    )
                    for evidence
                    in item.evidence_sources
                ],
                data_sufficient=data_sufficient,
            )
            for item in hypotheses
        ]
        session.add_all(cause_records)

        anomaly_evidence = dict(
            anomaly.evidence_json or {}
        )
        anomaly_evidence["cause_analysis"] = {
            "data_sufficient": data_sufficient,
            "has_historical_cases": bool(cases),
        }
        anomaly.evidence_json = anomaly_evidence
        anomaly.status = "已归因"

        await session.commit()

        for cause_record in cause_records:
            await session.refresh(cause_record)

    except Exception:
        await session.rollback()
        raise

    return CauseAnalysisResult(
        anomaly_id=anomaly.id,
        data_sufficient=data_sufficient,
        has_historical_cases=bool(cases),
        causes=[
            AnomalyCauseRead.model_validate(
                cause_record
            )
            for cause_record in cause_records
        ],
    )


async def get_anomaly_cause_result(
    session: AsyncSession,
    anomaly_id: int,
) -> CauseAnalysisResult | None:
    """查询异常已有的原因假设。

    Args:
        session: 数据库异步会话。
        anomaly_id: 异常编号。

    Returns:
        已保存的归因结果；异常或原因不存在时返回 None。
    """
    anomaly = await session.get(
        AnomalyRecord,
        anomaly_id,
    )

    if anomaly is None:
        return None

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
        return None

    analysis_meta = (
        anomaly.evidence_json or {}
    ).get("cause_analysis", {})

    has_historical_cases = bool(
        analysis_meta.get(
            "has_historical_cases",
            any(
                source.get("type") == "case"
                for cause in causes
                for source in (
                    cause.evidence_sources or []
                )
            ),
        )
    )
    data_sufficient = bool(
        analysis_meta.get(
            "data_sufficient",
            causes[0].data_sufficient,
        )
    )

    return CauseAnalysisResult(
        anomaly_id=anomaly.id,
        data_sufficient=data_sufficient,
        has_historical_cases=(
            has_historical_cases
        ),
        causes=[
            AnomalyCauseRead.model_validate(cause)
            for cause in causes
        ],
    )
