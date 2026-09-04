from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdGroup,
    AdMetricRealtime,
    AdPlan,
    AnomalyRecord,
    Audience,
    Channel,
    Creative,
    SalesFeedback,
)


_SALES_FEEDBACK_MIN_COUNT = 3
_SALES_FEEDBACK_FRESH_HOURS = 24


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
