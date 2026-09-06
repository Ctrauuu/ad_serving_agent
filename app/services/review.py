import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActionExecution,
    AdMetricRealtime,
    AnomalyCause,
    AnomalyRecord,
    Campaign,
    CaseLibrary,
    KnowledgeDoc,
    ReviewReport,
    Strategy,
)
from app.infrastructure.milvus import milvus_client
from app.schemas import (
    ReviewCaseCandidate,
    ReviewCaseType,
    ReviewGenerationOutput,
    StructuredGoal,
)
from app.services.embedding import embed_goal, embed_text
from app.services.goal import get_goal_llm

_review_parser = PydanticOutputParser(
    pydantic_object=ReviewGenerationOutput,
)

_REVIEW_SYSTEM_PROMPT = f"""
你是广告投放复盘分析助手。请根据输入的确定性事实，
生成复盘叙事结论及可检索的历史案例。

规则：
1. 只能依据输入事实，不得虚构指标、异常、动作或案例。
2. 策略是否达标必须以 strategy_evaluation 为准；
   动作是否改善必须以 interventions 中的 verdict 为准。
3. 标记“数据不足”的指标或动作，只能说明数据不足，
   不得得出有效或失败结论。
4. cases 中的 strategy、anomaly、intervention 仅在输入存在
   对应事实时生成；案例必须包含可复用的具体结论。
5. effectiveness 只能是“有效”或“失败”，并应与输入证据一致。
6. 若无异常或动作，可以只沉淀 strategy 类型案例。
7. 必须输出合法 JSON。

{_review_parser.get_format_instructions()}
"""


def _to_json(value: object) -> str:
    """将复盘上下文转换为稳定、可读的 JSON 提示词文本。

    Args:
        value: 由确定性服务汇总出的复盘上下文。

    Returns:
        保留中文字符并能处理 Decimal、datetime 等值的 JSON 文本。
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
    )


async def generate_review_narrative(
    context: dict[str, Any],
) -> ReviewGenerationOutput:
    """调用模型生成复盘叙事结论和待沉淀案例。

    Args:
        context: collect_review_context 返回的确定性复盘事实。

    Returns:
        经 Pydantic 校验后的复盘结论与案例集合。

    Raises:
        ValueError: 模型未返回文本，或返回内容不符合约定结构时抛出。
    """
    response = await get_goal_llm().ainvoke(
        [
            SystemMessage(
                content=_REVIEW_SYSTEM_PROMPT,
            ),
            HumanMessage(
                content=(
                    "以下是本次活动复盘的确定性事实：\n"
                    f"{_to_json(context)}"
                ),
            ),
        ]
    )

    if not isinstance(response.content, str):
        raise ValueError("模型未返回文本内容")

    try:
        return _review_parser.parse(response.content)
    except OutputParserException as exc:
        raise ValueError(
            "模型返回内容不符合复盘结构"
        ) from exc


def _ratio_as_float(
    numerator: Decimal,
    denominator: Decimal,
    precision: str,
) -> float | None:
    """安全计算指标比例并转换为 JSON 可存储的浮点数。

    Args:
        numerator: 指标分子。
        denominator: 指标分母。
        precision: Decimal 量化精度，例如 "0.01"。

    Returns:
        分母为零时返回 None；否则返回按指定精度四舍五入的比例。
    """
    if denominator == 0:
        return None

    return float(
        (numerator / denominator).quantize(
            Decimal(precision),
            rounding=ROUND_HALF_UP,
        )
    )


def _summarize_metric_rows(
    rows: list[AdMetricRealtime],
) -> dict[str, int | float | None]:
    """累计多个同一粒度指标窗口并重新计算比例指标。

    Args:
        rows: 同一活动、维度和时间窗口粒度的指标记录。

    Returns:
        累计基础指标及由累计值重新计算的比例指标。
        空列表时基础值为 0，比例指标为 None。
    """
    impression = sum(row.impression for row in rows)
    click = sum(row.click for row in rows)
    cost = sum(
        (row.cost for row in rows),
        start=Decimal("0"),
    )
    lead = sum(row.lead for row in rows)
    valid_lead = sum(row.valid_lead for row in rows)
    order = sum(row.order for row in rows)
    revenue = sum(
        (
            row.cost * (row.roi or Decimal("0"))
            for row in rows
        ),
        start=Decimal("0"),
    )

    return {
        "impression": impression,
        "click": click,
        "cost": float(cost),
        "lead": lead,
        "valid_lead": valid_lead,
        "order": order,
        "ctr": _ratio_as_float(
            Decimal(click),
            Decimal(impression),
            "0.000001",
        ),
        "cpc": _ratio_as_float(
            cost,
            Decimal(click),
            "0.01",
        ),
        "cpa": _ratio_as_float(
            cost,
            Decimal(lead),
            "0.01",
        ),
        "valid_lead_rate": _ratio_as_float(
            Decimal(valid_lead),
            Decimal(lead),
            "0.0001",
        ),
        "roi": _ratio_as_float(
            revenue,
            cost,
            "0.0001",
        ),
    }


async def get_overall_metrics(
    session: AsyncSession,
    campaign_id: int,
) -> dict[str, int | float | None]:
    """汇总活动全部日粒度指标并重新计算核心比例。

    Args:
        session: 数据库异步会话。
        campaign_id: 要复盘的活动编号。

    Returns:
        包含累计曝光、点击、消耗、线索、订单及比例指标的字典；
        没有日指标时，累计值为 0、比例指标为 None。

    Notes:
        只读取 dimension="campaign"、time_window="day" 的记录，
        避免把分钟、小时、日指标重复累计。
    """
    rows = list(
        await session.scalars(
            select(AdMetricRealtime).where(
                AdMetricRealtime.campaign_id
                == campaign_id,
                AdMetricRealtime.dimension
                == "campaign",
                AdMetricRealtime.dim_id == campaign_id,
                AdMetricRealtime.time_window == "day",
            )
        )
    )

    return {
        "data_days": len(rows),
        **_summarize_metric_rows(rows),
    }


def evaluate_strategy_metrics(
    expected_metrics: dict[str, Any] | None,
    overall_metrics: dict[str, int | float | None],
) -> dict[str, Any]:
    """对比策略预期指标与活动实际汇总指标。

    Args:
        expected_metrics: 已确认策略中的 expected_metrics。
        overall_metrics: get_overall_metrics 返回的活动实际指标。

    Returns:
        包含逐指标对比、达标统计和整体结论的字典。
        无法从现有数据计算的指标会标记为“数据不足”。

    Notes:
        CPA、CPC、日均消耗越低越好；CTR、有效线索率、
        点击转线索率和 ROI 越高越好。
    """
    if not expected_metrics:
        return {
            "verdict": "无预期指标",
            "met_count": 0,
            "unmet_count": 0,
            "unavailable_count": 0,
            "metrics": {},
        }

    data_days = int(overall_metrics["data_days"] or 0)
    click = int(overall_metrics["click"] or 0)
    lead = int(overall_metrics["lead"] or 0)
    cost = Decimal(str(overall_metrics["cost"] or 0))

    actual_values: dict[str, float | None] = {
        "cpa": overall_metrics["cpa"],
        "cpc": overall_metrics["cpc"],
        "ctr": overall_metrics["ctr"],
        "impression_to_click_rate": (
            overall_metrics["ctr"]
        ),
        "valid_lead_rate": (
            overall_metrics["valid_lead_rate"]
        ),
        "click_to_lead_rate": _ratio_as_float(
            Decimal(lead),
            Decimal(click),
            "0.0001",
        ),
        "cost_rate_daily": _ratio_as_float(
            cost,
            Decimal(data_days),
            "0.01",
        ),
        "roi": overall_metrics["roi"],
    }
    lower_is_better = {
        "cpa",
        "cpc",
        "cost_rate_daily",
    }
    rate_metrics = {
        "ctr",
        "impression_to_click_rate",
        "valid_lead_rate",
        "click_to_lead_rate",
    }

    comparisons: dict[str, dict[str, Any]] = {}
    met_count = 0
    unmet_count = 0
    unavailable_count = 0

    for metric, raw_expected in expected_metrics.items():
        try:
            expected = Decimal(str(raw_expected))
        except Exception:
            comparisons[metric] = {
                "expected": raw_expected,
                "actual": None,
                "status": "数据不足",
                "reason": "预期指标不是数值",
            }
            unavailable_count += 1
            continue

        if metric in rate_metrics and expected > 1:
            expected = expected / Decimal("100")

        actual = actual_values.get(metric)

        if actual is None:
            comparisons[metric] = {
                "expected": float(expected),
                "actual": None,
                "status": "数据不足",
                "reason": "当前没有可比实际指标",
            }
            unavailable_count += 1
            continue

        actual_decimal = Decimal(str(actual))
        difference = actual_decimal - expected
        achieved = (
            actual_decimal <= expected
            if metric in lower_is_better
            else actual_decimal >= expected
        )

        comparisons[metric] = {
            "expected": float(expected),
            "actual": float(actual_decimal),
            "difference": float(difference),
            "difference_rate": _ratio_as_float(
                difference,
                abs(expected),
                "0.0001",
            ),
            "direction": (
                "越低越好"
                if metric in lower_is_better
                else "越高越好"
            ),
            "status": "达标" if achieved else "未达标",
        }

        if achieved:
            met_count += 1
        else:
            unmet_count += 1

    if met_count + unmet_count == 0:
        verdict = "无可对比指标"
    elif unmet_count == 0:
        verdict = "达标"
    elif met_count == 0:
        verdict = "未达标"
    else:
        verdict = "部分达标"

    return {
        "verdict": verdict,
        "met_count": met_count,
        "unmet_count": unmet_count,
        "unavailable_count": unavailable_count,
        "metrics": comparisons,
    }


def get_action_effect_windows(
    executed_at: datetime,
) -> tuple[datetime, datetime, datetime, datetime]:
    """计算用于评估干预效果的前后完整小时窗口。

    Args:
        executed_at: 动作实际执行完成时间，使用 UTC 无时区时间。

    Returns:
        依次返回前窗口开始、前窗口结束、后窗口开始、后窗口结束。
        所有窗口均为左闭右开区间。

    Notes:
        动作若发生在某小时中间，会跳过该不完整小时，
        避免小时聚合数据同时混入动作前后效果。
    """
    action_hour = executed_at.replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    before_start = action_hour - timedelta(hours=2)
    before_end = action_hour

    after_start = (
        action_hour
        if executed_at == action_hour
        else action_hour + timedelta(hours=1)
    )
    after_end = after_start + timedelta(hours=2)

    return (
        before_start,
        before_end,
        after_start,
        after_end,
    )


async def get_action_window_metrics(
    session: AsyncSession,
    action: ActionExecution,
) -> dict[str, Any]:
    """读取一条广告组动作前后两个完整小时的聚合指标。

    Args:
        session: 数据库异步会话。
        action: 已执行的广告组动作记录。

    Returns:
        包含动作编号、前后时间窗口、窗口指标与数据完整标记的字典。

    Raises:
        ValueError: 动作不是广告组动作，或缺少执行完成时间。
    """
    if action.target_type != "ad_group":
        raise ValueError("当前仅支持广告组动作效果评估")

    if action.executed_at is None:
        raise ValueError("动作缺少执行时间，无法评估效果")

    (
        before_start,
        before_end,
        after_start,
        after_end,
    ) = get_action_effect_windows(action.executed_at)

    before_rows = list(
        await session.scalars(
            select(AdMetricRealtime).where(
                AdMetricRealtime.campaign_id
                == action.campaign_id,
                AdMetricRealtime.dimension
                == "ad_group",
                AdMetricRealtime.dim_id
                == action.target_id,
                AdMetricRealtime.time_window == "hour",
                AdMetricRealtime.window_start
                >= before_start,
                AdMetricRealtime.window_start
                < before_end,
            )
        )
    )
    after_rows = list(
        await session.scalars(
            select(AdMetricRealtime).where(
                AdMetricRealtime.campaign_id
                == action.campaign_id,
                AdMetricRealtime.dimension
                == "ad_group",
                AdMetricRealtime.dim_id
                == action.target_id,
                AdMetricRealtime.time_window == "hour",
                AdMetricRealtime.window_start
                >= after_start,
                AdMetricRealtime.window_start
                < after_end,
            )
        )
    )

    return {
        "action_id": action.id,
        "target_id": action.target_id,
        "before": {
            "window_start": before_start.isoformat(),
            "window_end": before_end.isoformat(),
            "data_hours": len(before_rows),
            "data_sufficient": len(before_rows) == 2,
            **_summarize_metric_rows(before_rows),
        },
        "after": {
            "window_start": after_start.isoformat(),
            "window_end": after_end.isoformat(),
            "data_hours": len(after_rows),
            "data_sufficient": len(after_rows) == 2,
            **_summarize_metric_rows(after_rows),
        },
    }


def evaluate_action_effect(
    action: ActionExecution,
    window_metrics: dict[str, Any],
) -> dict[str, Any]:
    """根据动作前后窗口指标评价干预效果。

    Args:
        action: 已执行的广告组动作记录。
        window_metrics: get_action_window_metrics 返回的窗口指标。

    Returns:
        包含前后指标变化、数据完整性和确定性评价结论的字典。

    Notes:
        CPA 越低越好；有效线索率、ROI 越高越好。
        消耗变化只作为证据展示，不单独决定动作是否有效。
    """
    before = window_metrics["before"]
    after = window_metrics["after"]
    data_sufficient = (
        before["data_sufficient"]
        and after["data_sufficient"]
    )

    changes: dict[str, dict[str, float | None]] = {}

    for metric in (
        "cost",
        "cpa",
        "valid_lead_rate",
        "roi",
    ):
        before_value = before[metric]
        after_value = after[metric]

        if before_value is None or after_value is None:
            changes[metric] = {
                "before": before_value,
                "after": after_value,
                "difference": None,
                "change_rate": None,
            }
            continue

        before_decimal = Decimal(str(before_value))
        after_decimal = Decimal(str(after_value))
        difference = after_decimal - before_decimal

        changes[metric] = {
            "before": float(before_decimal),
            "after": float(after_decimal),
            "difference": float(difference),
            "change_rate": _ratio_as_float(
                difference,
                abs(before_decimal),
                "0.0001",
            ),
        }

    if not data_sufficient:
        verdict = "数据不足"
    else:
        improved_count = 0
        worsened_count = 0

        cpa_change = changes["cpa"]["difference"]
        if cpa_change is not None:
            if cpa_change < 0:
                improved_count += 1
            elif cpa_change > 0:
                worsened_count += 1

        for metric in ("valid_lead_rate", "roi"):
            change = changes[metric]["difference"]

            if change is None:
                continue

            if change > 0:
                improved_count += 1
            elif change < 0:
                worsened_count += 1

        if improved_count == 0 and worsened_count == 0:
            verdict = "无可比质量指标"
        elif improved_count > 0 and worsened_count == 0:
            verdict = "改善"
        elif worsened_count > 0 and improved_count == 0:
            verdict = "恶化"
        else:
            verdict = "无明显变化"

    return {
        "action_id": action.id,
        "action_type": action.action_type,
        "target_id": action.target_id,
        "data_sufficient": data_sufficient,
        "verdict": verdict,
        "before": before,
        "after": after,
        "changes": changes,
    }


async def get_intervention_evaluations(
    session: AsyncSession,
    campaign_id: int,
) -> dict[str, dict[str, Any]]:
    """汇总活动内所有成功动作的前后效果评价。

    Args:
        session: 数据库异步会话。
        campaign_id: 要复盘的活动编号。

    Returns:
        以 action_{id} 为键的动作效果评价字典。
        单条动作无法取数时保留“数据不足”结果，
        不影响其他动作继续完成评价。
    """
    actions = list(
        await session.scalars(
            select(ActionExecution)
            .where(
                ActionExecution.campaign_id
                == campaign_id,
                ActionExecution.status == "成功",
            )
            .order_by(
                ActionExecution.executed_at,
                ActionExecution.id,
            )
        )
    )

    evaluations: dict[str, dict[str, Any]] = {}

    for action in actions:
        try:
            window_metrics = await get_action_window_metrics(
                session,
                action,
            )
            evaluation = evaluate_action_effect(
                action,
                window_metrics,
            )
        except ValueError as exc:
            evaluation = {
                "action_id": action.id,
                "action_type": action.action_type,
                "target_id": action.target_id,
                "data_sufficient": False,
                "verdict": "数据不足",
                "reason": str(exc),
            }

        evaluations[f"action_{action.id}"] = evaluation

    return evaluations


async def get_latest_confirmed_strategy(
    session: AsyncSession,
    campaign_id: int,
) -> Strategy | None:
    """读取活动最新版本的已确认投放策略。

    Args:
        session: 数据库异步会话。
        campaign_id: 要复盘的活动编号。

    Returns:
        版本最高的已确认策略；活动尚无已确认策略时返回 None。
    """
    return await session.scalar(
        select(Strategy)
        .where(
            Strategy.campaign_id == campaign_id,
            Strategy.status == "已确认",
        )
        .order_by(
            Strategy.version.desc(),
            Strategy.id.desc(),
        )
    )


async def get_review_anomalies(
    session: AsyncSession,
    campaign_id: int,
) -> list[dict[str, Any]]:
    """读取活动异常及其已有原因假设，构建复盘证据上下文。

    Args:
        session: 数据库异步会话。
        campaign_id: 要复盘的活动编号。

    Returns:
        因按发现时间排序的异常列表；每条异常包含对应原假设。
        活动没有异常时返回空列表。
    """
    anomalies = list(
        await session.scalars(
            select(AnomalyRecord)
            .where(
                AnomalyRecord.campaign_id
                == campaign_id
            )
            .order_by(
                AnomalyRecord.detected_at,
                AnomalyRecord.id,
            )
        )
    )

    if not anomalies:
        return []

    anomaly_ids = [
        anomaly.id
        for anomaly in anomalies
    ]
    causes = list(
        await session.scalars(
            select(AnomalyCause)
            .where(
                AnomalyCause.anomaly_id.in_(
                    anomaly_ids
                )
            )
            .order_by(
                AnomalyCause.anomaly_id,
                AnomalyCause.confidence.desc(),
                AnomalyCause.id,
            )
        )
    )

    causes_by_anomaly: dict[
        int,
        list[dict[str, Any]],
    ] = {
        anomaly_id: []
        for anomaly_id in anomaly_ids
    }

    for cause in causes:
        causes_by_anomaly[cause.anomaly_id].append(
            {
                "id": cause.id,
                "cause_type": cause.cause_type,
                "hypothesis": cause.hypothesis,
                "confidence": float(cause.confidence),
                "evidence_sources": (
                    cause.evidence_sources or []
                ),
                "data_sufficient": cause.data_sufficient,
            }
        )

    return [
        {
            "id": anomaly.id,
            "target_type": anomaly.target_type,
            "target_id": anomaly.target_id,
            "anomaly_type": anomaly.anomaly_type,
            "metric": anomaly.metric,
            "metric_value": (
                float(anomaly.metric_value)
                if anomaly.metric_value is not None
                else None
            ),
            "baseline_value": (
                float(anomaly.baseline_value)
                if anomaly.baseline_value is not None
                else None
            ),
            "severity": anomaly.severity,
            "status": anomaly.status,
            "evidence": anomaly.evidence_json or {},
            "detected_at": anomaly.detected_at.isoformat(),
            "causes": causes_by_anomaly[anomaly.id],
        }
        for anomaly in anomalies
    ]


async def collect_review_context(
    session: AsyncSession,
    campaign_id: int,
) -> dict[str, Any]:
    """汇总生成复盘报告所需的全部确定性业务上下文。

    Args:
        session: 数据库异步会话。
        campaign_id: 要复盘的活动编号。

    Returns:
        包含整体实际指标、策略预期对比、异常原因与干预效果的字典。
    """
    overall_metrics = await get_overall_metrics(
        session,
        campaign_id,
    )
    strategy = await get_latest_confirmed_strategy(
        session,
        campaign_id,
    )
    strategy_evaluation = evaluate_strategy_metrics(
        strategy.expected_metrics if strategy else None,
        overall_metrics,
    )
    anomalies = await get_review_anomalies(
        session,
        campaign_id,
    )
    interventions = await get_intervention_evaluations(
        session,
        campaign_id,
    )

    return {
        "campaign_id": campaign_id,
        "overall_metrics": overall_metrics,
        "strategy": (
            {
                "id": strategy.id,
                "version": strategy.version,
                "channel_mix": strategy.channel_mix,
                "budget_split": strategy.budget_split,
                "expected_metrics": (
                    strategy.expected_metrics or {}
                ),
                "risk_notes": strategy.risk_notes,
            }
            if strategy is not None
            else None
        ),
        "strategy_evaluation": strategy_evaluation,
        "anomalies": anomalies,
        "interventions": interventions,
    }


async def save_review_report(
    session: AsyncSession,
    campaign_id: int,
    context: dict[str, Any],
    narrative: ReviewGenerationOutput,
) -> ReviewReport:
    """以新版本保存一次复盘报告，不覆盖已有历史报告。

    Args:
        session: 数据库异步会话。
        campaign_id: 已结束活动的编号。
        context: collect_review_context 返回的确定性复盘事实。
        narrative: generate_review_narrative 返回的模型叙事结果。

    Returns:
        已写入当前会话、拥有新版本号的复盘报告。

    Notes:
        事务由调用方统一提交；本函数仅 flush 以取得主键。
    """
    latest_version = await session.scalar(
        select(func.max(ReviewReport.version)).where(
            ReviewReport.campaign_id == campaign_id
        )
    )
    report = ReviewReport(
        campaign_id=campaign_id,
        version=int(latest_version or 0) + 1,
        overall_metrics=context["overall_metrics"],
        strategy_evaluation=context["strategy_evaluation"],
        intervention_evaluation=context["interventions"],
        reusable_conclusion=narrative.reusable_conclusion,
        lessons=narrative.lessons,
        improvement=narrative.improvement,
    )
    session.add(report)
    await session.flush()

    return report


async def get_latest_review_report(
    session: AsyncSession,
    campaign_id: int,
) -> ReviewReport | None:
    """读取活动最新版本的复盘报告。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。

    Returns:
        版本最高的复盘报告；尚未复盘时返回 None。
    """
    return await session.scalar(
        select(ReviewReport)
        .where(ReviewReport.campaign_id == campaign_id)
        .order_by(
            ReviewReport.version.desc(),
            ReviewReport.id.desc(),
        )
    )


async def save_review_cases(
    session: AsyncSession,
    campaign_id: int,
    candidates: list[ReviewCaseCandidate],
) -> list[CaseLibrary]:
    """保存复盘生成的结构化案例，并复用相同场景的已有案例。

    Args:
        session: 数据库异步会话。
        campaign_id: 已结束活动的编号。
        candidates: 模型生成并经过 schema 校验的待沉淀案例。

    Returns:
        本次新增或更新后的案例记录列表。

    Notes:
        相同活动、案例类型与场景描述视为同一案例；
        重复复盘时更新其结论而非持续插入重复向量。
    """
    existing_cases = list(
        await session.scalars(
            select(CaseLibrary).where(
                CaseLibrary.campaign_id == campaign_id
            )
        )
    )
    cases_by_key = {
        (case.case_type, case.scene_desc): case
        for case in existing_cases
    }
    saved_cases: list[CaseLibrary] = []

    for candidate in candidates:
        key = (candidate.case_type, candidate.scene_desc)
        case = cases_by_key.get(key)

        if case is None:
            case = CaseLibrary(
                case_type=candidate.case_type,
                campaign_id=campaign_id,
                scene_desc=candidate.scene_desc,
                anomaly_type=candidate.anomaly_type,
                cause=candidate.cause,
                action=candidate.action,
                effectiveness=candidate.effectiveness,
                conclusion=candidate.conclusion,
            )
            session.add(case)
            cases_by_key[key] = case
            saved_cases.append(case)
            continue

        case.anomaly_type = candidate.anomaly_type
        case.cause = candidate.cause
        case.action = candidate.action
        case.effectiveness = candidate.effectiveness
        case.conclusion = candidate.conclusion

        if case not in saved_cases:
            saved_cases.append(case)

    await session.flush()

    return saved_cases


def format_review_case(
    case: CaseLibrary,
) -> str:
    """将复盘案例转为稳定的 Embedding 文本。

    Args:
        case: 已落库的复盘案例。

    Returns:
        包含场景、异常、原因、动作、结果与结论的语义文本。
    """
    return (
        "投放复盘案例：\n"
        + _to_json(
            {
                "case_type": case.case_type,
                "scene_desc": case.scene_desc,
                "anomaly_type": case.anomaly_type,
                "cause": case.cause,
                "action": case.action,
                "effectiveness": case.effectiveness,
                "conclusion": case.conclusion,
            }
        )
    )


async def index_review_cases(
    session: AsyncSession,
    campaign_id: int,
    cases: list[CaseLibrary],
) -> None:
    """将复盘案例写入其对应的 Milvus 召回集合。

    Args:
        session: 数据库异步会话。
        campaign_id: 所属活动编号。
        cases: 已完成 flush、已拥有案例编号的案例记录。

    Returns:
        无返回值；成功后会回写每条案例的 vector_id。

    Raises:
        ValueError: 策略案例关联的 structured_goal 不符合既有 schema 时抛出。

    Notes:
        strategy 案例关联确认策略的 goal_vector；
        anomaly 与 intervention 案例分别以 case_id 写入各自集合。
    """
    strategy_cases = [
        case
        for case in cases
        if case.case_type == "strategy"
    ]

    if strategy_cases:
        campaign = await session.get(Campaign, campaign_id)
        strategy = await get_latest_confirmed_strategy(
            session,
            campaign_id,
        )

        if (
            campaign is not None
            and campaign.structured_goal is not None
            and strategy is not None
        ):
            try:
                goal = StructuredGoal.model_validate(
                    campaign.structured_goal
                )
            except ValidationError as exc:
                raise ValueError(
                    "活动 structured_goal 格式无效"
                ) from exc

            goal_vector = await embed_goal(
                goal,
                text_type="document",
            )
            await milvus_client.upsert_strategy_vector(
                strategy_id=strategy.id,
                campaign_id=campaign_id,
                goal_vector=goal_vector,
            )

            for case in strategy_cases:
                case.vector_id = str(strategy.id)

    for case in cases:
        if case.case_type == "anomaly":
            vector = await embed_text(
                format_review_case(case),
                text_type="document",
            )
            await milvus_client.upsert_anomaly_case_vector(
                case_id=case.id,
                scene_vector=vector,
            )
            case.vector_id = str(case.id)

        if case.case_type == "intervention":
            vector = await embed_text(
                format_review_case(case),
                text_type="document",
            )
            await milvus_client.upsert_intervention_case_vector(
                case_id=case.id,
                intervention_vector=vector,
            )
            case.vector_id = str(case.id)

    await session.flush()


def format_review_document(
    report: ReviewReport,
) -> str:
    """将完整复盘报告转换为知识库的 Embedding 文本。

    Args:
        report: 已持久化的活动复盘报告。

    Returns:
        供后续知识检索使用的稳定报告文本。
    """
    return (
        "广告投放复盘报告：\n"
        + _to_json(
            {
                "campaign_id": report.campaign_id,
                "version": report.version,
                "overall_metrics": report.overall_metrics,
                "strategy_evaluation": report.strategy_evaluation,
                "intervention_evaluation": (
                    report.intervention_evaluation
                ),
                "reusable_conclusion": (
                    report.reusable_conclusion
                ),
                "lessons": report.lessons,
                "improvement": report.improvement,
            }
        )
    )


async def upsert_review_knowledge_doc(
    session: AsyncSession,
    report: ReviewReport,
) -> KnowledgeDoc:
    """保存复盘知识文档并同步其全文向量。

    Args:
        session: 数据库异步会话。
        report: 已保存且拥有编号的复盘报告。

    Returns:
        与该复盘版本对应的知识文档记录。

    Notes:
        首版按整篇报告建立单个向量，chunk_count 固定为 1；
        相同 source_ref 重试时更新原文档和原向量。
    """
    source_ref = f"review_report:{report.id}"
    document = await session.scalar(
        select(KnowledgeDoc).where(
            KnowledgeDoc.source_ref == source_ref
        )
    )

    if document is None:
        document = KnowledgeDoc(
            title=(
                f"活动 {report.campaign_id} "
                f"投放复盘 v{report.version}"
            ),
            doc_type="review_report",
            source_ref=source_ref,
            chunk_count=1,
            parse_status="已完成",
        )
        session.add(document)
    else:
        document.title = (
            f"活动 {report.campaign_id} "
            f"投放复盘 v{report.version}"
        )
        document.doc_type = "review_report"
        document.chunk_count = 1
        document.parse_status = "已完成"

    await session.flush()

    vector = await embed_text(
        format_review_document(report),
        text_type="document",
    )
    await milvus_client.upsert_knowledge_vector(
        knowledge_doc_id=document.id,
        vector=vector,
    )
    document.ragflow_doc_id = str(document.id)

    await session.flush()

    return document


async def generate_campaign_review(
    session: AsyncSession,
    campaign: Campaign,
) -> ReviewReport:
    """为已结束活动生成、保存并沉淀一版完整复盘。

    Args:
        session: 数据库异步会话。
        campaign: 当前用户已授权访问的活动记录。

    Returns:
        已提交并刷新后的新版本复盘报告。

    Raises:
        ValueError: 活动尚未结束，无法开始复盘。
        RuntimeError: 模型、Embedding 或 Milvus 调用失败时向上抛出。
    """
    if campaign.status != "已结束":
        raise ValueError("活动尚未结束，不能生成复盘")

    try:
        context = await collect_review_context(
            session,
            campaign.id,
        )
        narrative = await generate_review_narrative(context)
        report = await save_review_report(
            session,
            campaign.id,
            context,
            narrative,
        )
        cases = await save_review_cases(
            session,
            campaign.id,
            narrative.cases,
        )
        await index_review_cases(
            session,
            campaign.id,
            cases,
        )
        await upsert_review_knowledge_doc(session, report)

        await session.commit()
        await session.refresh(report)
    except Exception:
        await session.rollback()
        raise

    return report


async def list_review_cases(
    session: AsyncSession,
    case_type: ReviewCaseType | None = None,
) -> list[CaseLibrary]:
    """按可选案例类型查询已沉淀的历史案例。

    Args:
        session: 数据库异步会话。
        case_type: 可选的 strategy、anomaly 或 intervention 类型。

    Returns:
        按创建时间倒序排列的案例记录列表。
    """
    statement = select(CaseLibrary).order_by(
        CaseLibrary.created_at.desc(),
        CaseLibrary.id.desc(),
    )

    if case_type is not None:
        statement = statement.where(
            CaseLibrary.case_type == case_type
        )

    return list(await session.scalars(statement))