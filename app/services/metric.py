import json
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ad_platform import (
    call_ad_platform_tool,
)
from app.infrastructure.redis import redis_client
from app.models import (
    AdGroup,
    AdMetricRealtime,
    AdPlan,
    BudgetConsumption,
    Campaign,
)
from app.schemas import (
    BudgetConsumptionRead,
    CampaignBudgetResult,
    MetricSyncError,
    MetricSyncResult,
    MetricDimension,
    RealtimeMetric,
    RealtimeMetricResult,
    MetricTrendPoint,
    MetricTrendResult,
    MetricTrendSeries,
    MetricTrendWindow,
)

_CENT = Decimal("0.01")


def _window_start(
    data_time: datetime,
    window: str,
) -> datetime:
    """计算指标窗口起点。

    Args:
        data_time: 指标采集时间。
        window: 聚合时间窗口。

    Returns:
        返回类型为 datetime 的执行结果。
    """
    if window == "minute":
        return data_time.replace(
            second=0,
            microsecond=0,
        )

    if window == "hour":
        return data_time.replace(
            minute=0,
            second=0,
            microsecond=0,
        )

    return data_time.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _parse_data_time(value: object) -> datetime:
    """解析并标准化平台时间。

    Args:
        value: 待处理的输入值。

    Returns:
        返回类型为 datetime 的执行结果。
    """
    parsed = datetime.fromisoformat(str(value))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return (
        parsed.astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def _money(value: object) -> Decimal:
    """量化两位小数金额。

    Args:
        value: 待处理的输入值。

    Returns:
        返回类型为 Decimal 的执行结果。
    """
    return Decimal(str(value)).quantize(
        _CENT,
        rounding=ROUND_HALF_UP,
    )


def _ratio(
    numerator: Decimal,
    denominator: Decimal,
    precision: str,
) -> Decimal | None:
    """安全计算量化比率。

    Args:
        numerator: 函数输入参数。
        denominator: 函数输入参数。
        precision: 函数输入参数。

    Returns:
        返回类型为 Decimal | None 的执行结果。
    """
    if denominator == 0:
        return None

    return (numerator / denominator).quantize(
        Decimal(precision),
        rounding=ROUND_HALF_UP,
    )


def _metric_payload(
    row: AdMetricRealtime,
) -> dict[str, Any]:
    """转换 Redis 指标数据。

    Args:
        row: 指标记录。

    Returns:
        返回类型为 dict[str, Any] 的执行结果。
    """
    now = datetime.now(timezone.utc).replace(
        tzinfo=None
    )
    is_stale = (
        now - row.collected_at
        > timedelta(minutes=10)
    )

    return {
        "dimension": row.dimension,
        "dim_id": row.dim_id,
        "time_window": row.time_window,
        "window_start": row.window_start.isoformat(),
        "impression": row.impression,
        "click": row.click,
        "cost": float(row.cost),
        "lead": row.lead,
        "valid_lead": row.valid_lead,
        "order": row.order,
        "ctr": (
            float(row.ctr)
            if row.ctr is not None
            else None
        ),
        "cpc": (
            float(row.cpc)
            if row.cpc is not None
            else None
        ),
        "cpa": (
            float(row.cpa)
            if row.cpa is not None
            else None
        ),
        "roi": (
            float(row.roi)
            if row.roi is not None
            else None
        ),
        "collected_at": row.collected_at.isoformat(),
        "is_stale": is_stale,
    }


async def _save_metric(
    session: AsyncSession,
    campaign_id: int,
    key: tuple[str, int, str, datetime],
    totals: dict[str, Any],
) -> AdMetricRealtime:
    """累计保存聚合指标。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。
        key: 聚合唯一键。
        totals: 窗口累计指标。

    Returns:
        返回类型为 AdMetricRealtime 的执行结果。
    """
    dimension, dim_id, window, window_start = key

    row = await session.scalar(
        select(AdMetricRealtime).where(
            AdMetricRealtime.campaign_id
            == campaign_id,
            AdMetricRealtime.dimension
            == dimension,
            AdMetricRealtime.dim_id == dim_id,
            AdMetricRealtime.time_window
            == window,
            AdMetricRealtime.window_start
            == window_start,
        )
    )

    if row is None:
        row = AdMetricRealtime(
            campaign_id=campaign_id,
            dimension=dimension,
            dim_id=dim_id,
            time_window=window,
            window_start=window_start,
            impression=0,
            click=0,
            cost=Decimal("0"),
            lead=0,
            valid_lead=0,
            order=0,
            collected_at=totals["data_time"],
        )
        session.add(row)

    previous_revenue = (
        row.cost * row.roi
        if row.roi is not None
        else Decimal("0")
    )

    row.impression += totals["impression"]
    row.click += totals["click"]
    row.cost = _money(row.cost + totals["cost"])
    row.lead += totals["lead"]
    row.valid_lead += totals["valid_lead"]
    row.order += totals["order"]
    row.collected_at = max(
        row.collected_at,
        totals["data_time"],
    )

    revenue = previous_revenue + totals["revenue"]

    row.ctr = _ratio(
        Decimal(row.click),
        Decimal(row.impression),
        "0.000001",
    )
    row.cpc = _ratio(
        row.cost,
        Decimal(row.click),
        "0.01",
    )
    row.cpa = _ratio(
        row.cost,
        Decimal(row.lead),
        "0.01",
    )
    row.roi = _ratio(
        revenue,
        row.cost,
        "0.0001",
    )

    return row


async def _save_budget(
    session: AsyncSession,
    campaign_id: int,
    target_type: str,
    target_id: int,
    budget_total: Decimal,
    cost: Decimal,
) -> BudgetConsumption:
    """累计更新预算状态。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。
        target_type: 预算目标类型。
        target_id: 预算目标编号。
        budget_total: 预算总额。
        cost: 新增消耗。

    Returns:
        返回类型为 BudgetConsumption 的执行结果。
    """
    row = await session.scalar(
        select(BudgetConsumption).where(
            BudgetConsumption.target_type
            == target_type,
            BudgetConsumption.target_id
            == target_id,
        )
    )

    if row is None:
        row = BudgetConsumption(
            campaign_id=campaign_id,
            target_type=target_type,
            target_id=target_id,
            budget_total=budget_total,
            cost_total=Decimal("0"),
        )
        session.add(row)

    row.budget_total = budget_total
    row.cost_total = _money(row.cost_total + cost)
    row.remaining = max(
        _money(budget_total - row.cost_total),
        Decimal("0"),
    )
    row.cost_rate = _ratio(
        row.cost_total * Decimal("100"),
        budget_total,
        "0.01",
    )
    row.alert_status = (
        "超预算"
        if row.cost_total >= budget_total
        else "正常"
    )

    return row


async def sync_campaign_metrics(
    session: AsyncSession,
    campaign: Campaign,
) -> MetricSyncResult:
    """拉取、聚合并双写活动指标。

    Args:
        session: 数据库异步会话。
        campaign: 活动 ORM 对象。

    Returns:
        返回类型为 MetricSyncResult 的执行结果。
    """
    lock = redis_client.lock(
        f"metric:sync:lock:{campaign.id}",
        timeout=240,
    )

    if not await lock.acquire(blocking=False):
        raise ValueError("该活动的指标正在同步")

    try:
        task_rows = (
            await session.execute(
                select(AdGroup, AdPlan)
                .join(
                    AdPlan,
                    AdGroup.ad_plan_id == AdPlan.id,
                )
                .where(
                    AdGroup.campaign_id == campaign.id,
                    AdGroup.status == "已上线",
                    AdPlan.status == "已上线",
                )
                .order_by(AdGroup.id)
            )
        ).all()

        if not task_rows:
            raise ValueError("活动没有已上线的广告组")

        aggregates: dict[
            tuple[str, int, str, datetime],
            dict[str, Any],
        ] = {}
        group_costs: dict[int, Decimal] = {}
        plan_costs: dict[int, Decimal] = {}
        plans: dict[int, AdPlan] = {}
        errors: list[MetricSyncError] = []
        stale_groups = 0
        latest_time: datetime | None = None

        for group, plan in task_rows:
            plans[plan.id] = plan

            if not group.ad_platform_group_id:
                errors.append(
                    MetricSyncError(
                        ad_group_id=group.id,
                        message="缺少平台广告组ID",
                    )
                )
                continue

            try:
                metrics = await call_ad_platform_tool(
                    "get_ad_metrics",
                    {
                        "ad_platform_group_id": (
                            group.ad_platform_group_id
                        )
                    },
                )

                data_time = _parse_data_time(
                    metrics["data_time"]
                )
                impression = int(metrics["impressions"])
                click = int(metrics["clicks"])
                lead = int(metrics["lead"])
                valid_lead = int(
                    metrics["valid_lead"]
                )
                order = int(metrics["order"])
                cost = _money(metrics["spend"])
                revenue = _money(metrics["revenue"])

                if min(
                    impression,
                    click,
                    lead,
                    valid_lead,
                    order,
                ) < 0 or cost < 0 or revenue < 0:
                    raise ValueError("平台指标不能为负数")

                if not (
                    order
                    <= valid_lead
                    <= lead
                    <= click
                    <= impression
                ):
                    raise ValueError("平台指标层级关系错误")

            except Exception as exc:
                errors.append(
                    MetricSyncError(
                        ad_group_id=group.id,
                        message=str(exc)[:256],
                    )
                )
                continue

            latest_time = max(
                latest_time or data_time,
                data_time,
            )

            if (
                datetime.now(timezone.utc).replace(
                    tzinfo=None
                )
                - data_time
                > timedelta(minutes=10)
            ):
                stale_groups += 1

            group_costs[group.id] = cost
            plan_costs[plan.id] = (
                plan_costs.get(
                    plan.id,
                    Decimal("0"),
                )
                + cost
            )

            dimensions = [
                ("campaign", campaign.id),
                ("channel", plan.channel_id),
                ("ad_group", group.id),
            ]

            if group.creative_id is not None:
                dimensions.append(
                    ("creative", group.creative_id)
                )

            for dimension, dim_id in dimensions:
                for window in (
                    "minute",
                    "hour",
                    "day",
                ):
                    key = (
                        dimension,
                        dim_id,
                        window,
                        _window_start(
                            data_time,
                            window,
                        ),
                    )
                    totals = aggregates.setdefault(
                        key,
                        {
                            "impression": 0,
                            "click": 0,
                            "cost": Decimal("0"),
                            "lead": 0,
                            "valid_lead": 0,
                            "order": 0,
                            "revenue": Decimal("0"),
                            "data_time": data_time,
                        },
                    )

                    totals["impression"] += impression
                    totals["click"] += click
                    totals["cost"] += cost
                    totals["lead"] += lead
                    totals["valid_lead"] += valid_lead
                    totals["order"] += order
                    totals["revenue"] += revenue
                    totals["data_time"] = max(
                        totals["data_time"],
                        data_time,
                    )

        synced_groups = len(task_rows) - len(errors)

        if synced_groups == 0 or latest_time is None:
            raise ValueError("所有广告组指标同步失败")

        metric_rows = [
            await _save_metric(
                session,
                campaign.id,
                key,
                totals,
            )
            for key, totals in aggregates.items()
        ]

        campaign_cost = sum(
            group_costs.values(),
            Decimal("0"),
        )
        budget_rows = [
            await _save_budget(
                session,
                campaign.id,
                "campaign",
                campaign.id,
                campaign.budget_total,
                campaign_cost,
            )
        ]

        duration_days = max(
            (campaign.end_date - campaign.start_date).days
            + 1,
            1,
        )

        for plan_id, cost in plan_costs.items():
            plan = plans[plan_id]
            budget_rows.append(
                await _save_budget(
                    session,
                    campaign.id,
                    "ad_plan",
                    plan.id,
                    plan.budget_total,
                    cost,
                )
            )

        for group, _ in task_rows:
            if group.id not in group_costs:
                continue

            budget_rows.append(
                await _save_budget(
                    session,
                    campaign.id,
                    "ad_group",
                    group.id,
                    _money(
                        group.budget_daily
                        * duration_days
                    ),
                    group_costs[group.id],
                )
            )

        await session.flush()

        pipeline = redis_client.pipeline(
            transaction=True
        )

        for row in metric_rows:
            payload = json.dumps(
                _metric_payload(row),
                ensure_ascii=False,
            )

            if row.time_window == "minute":
                pipeline.hset(
                    (
                        f"metric:latest:"
                        f"{campaign.id}:"
                        f"{row.dimension}"
                    ),
                    str(row.dim_id),
                    payload,
                )

            if row.time_window == "hour":
                key = (
                    f"metric:hourly:"
                    f"{campaign.id}:"
                    f"{row.dimension}:"
                    f"{row.dim_id}"
                )
                score = int(
                    row.window_start.replace(
                        tzinfo=timezone.utc
                    ).timestamp()
                )
                pipeline.zremrangebyscore(
                    key,
                    score,
                    score,
                )
                pipeline.zadd(
                    key,
                    {payload: score},
                )

        for row in budget_rows:
            payload = json.dumps(
                {
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "budget_total": float(
                        row.budget_total
                    ),
                    "cost_total": float(
                        row.cost_total
                    ),
                    "cost_rate": (
                        float(row.cost_rate)
                        if row.cost_rate is not None
                        else None
                    ),
                    "remaining": (
                        float(row.remaining)
                        if row.remaining is not None
                        else None
                    ),
                    "alert_status": row.alert_status,
                },
                ensure_ascii=False,
            )
            pipeline.hset(
                f"budget:{campaign.id}",
                (
                    f"{row.target_type}:"
                    f"{row.target_id}"
                ),
                payload,
            )

        await pipeline.execute()
        await session.commit()

        return MetricSyncResult(
            campaign_id=campaign.id,
            status=(
                "partial"
                if errors
                else "success"
            ),
            synced_groups=synced_groups,
            failed_groups=len(errors),
            stale_groups=stale_groups,
            metric_rows=len(metric_rows),
            data_time=latest_time,
            errors=errors,
        )

    finally:
        if await lock.owned():
            await lock.release()


async def get_realtime_metrics(
    campaign_id: int,
    dimension: MetricDimension,
) -> RealtimeMetricResult:
    
    """读取 Redis 最新指标。

    Args:
        campaign_id: 活动编号。
        dimension: 指标维度。

    Returns:
        返回类型为 RealtimeMetricResult 的执行结果。
    """
    values = await cast(
    Awaitable[list[str]],
    redis_client.hvals(
        f"metric:latest:{campaign_id}:{dimension}"
    ),
)

    now = datetime.now(timezone.utc).replace(
        tzinfo=None
    )
    items: list[RealtimeMetric] = []

    for value in values:
        payload = json.loads(value)
        collected_at = _parse_data_time(
            payload["collected_at"]
        )
        payload["is_stale"] = (
            now - collected_at
            > timedelta(minutes=10)
        )
        items.append(
            RealtimeMetric.model_validate(payload)
        )

    items.sort(key=lambda item: item.dim_id)

    data_time = max(
        (
            item.collected_at
            for item in items
        ),
        default=None,
    )

    return RealtimeMetricResult(
        campaign_id=campaign_id,
        dimension=dimension,
        data_time=data_time,
        is_stale=(
            not items
            or any(item.is_stale for item in items)
        ),
        items=items,
    )


async def get_metric_trend(
    session: AsyncSession,
    campaign_id: int,
    dimension: MetricDimension,
    window: MetricTrendWindow,
) -> MetricTrendResult:
    """查询 MySQL 指标趋势。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。
        dimension: 指标维度。
        window: 聚合时间窗口。

    Returns:
        返回类型为 MetricTrendResult 的执行结果。
    """
    cutoff = (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        - timedelta(days=30)
    )

    rows = list(
        (
            await session.scalars(
                select(AdMetricRealtime)
                .where(
                    AdMetricRealtime.campaign_id
                    == campaign_id,
                    AdMetricRealtime.dimension
                    == dimension,
                    AdMetricRealtime.time_window
                    == window,
                    AdMetricRealtime.window_start
                    >= cutoff,
                )
                .order_by(
                    AdMetricRealtime.dim_id,
                    AdMetricRealtime.window_start,
                )
            )
        ).all()
    )

    grouped: dict[
        int,
        list[MetricTrendPoint],
    ] = {}

    for row in rows:
        grouped.setdefault(
            row.dim_id,
            [],
        ).append(
            MetricTrendPoint(
                window_start=row.window_start,
                impression=row.impression,
                click=row.click,
                cost=row.cost,
                lead=row.lead,
                valid_lead=row.valid_lead,
                order=row.order,
                ctr=row.ctr,
                cpc=row.cpc,
                cpa=row.cpa,
                roi=row.roi,
            )
        )

    data_time = max(
        (
            row.collected_at
            for row in rows
        ),
        default=None,
    )
    now = datetime.now(timezone.utc).replace(
        tzinfo=None
    )

    return MetricTrendResult(
        campaign_id=campaign_id,
        dimension=dimension,
        window=window,
        data_time=data_time,
        is_stale=(
            data_time is None
            or now - data_time
            > timedelta(minutes=10)
        ),
        series=[
            MetricTrendSeries(
                dim_id=dim_id,
                points=points,
            )
            for dim_id, points in grouped.items()
        ],
    )


async def get_campaign_budget(
    campaign_id: int,
) -> CampaignBudgetResult:
    """读取 Redis 预算状态。

    Args:
        campaign_id: 活动编号。

    Returns:
        返回类型为 CampaignBudgetResult 的执行结果。
    """
    values = await cast(
        Awaitable[list[str]],
        redis_client.hvals(
            f"budget:{campaign_id}"
        ),
    )

    items = [
        BudgetConsumptionRead.model_validate_json(
            value
        )
        for value in values
    ]

    target_order = {
        "campaign": 0,
        "ad_plan": 1,
        "ad_group": 2,
    }
    items.sort(
        key=lambda item: (
            target_order[item.target_type],
            item.target_id,
        )
    )

    latest_value = await cast(
        Awaitable[str | None],
        redis_client.hget(
            f"metric:latest:{campaign_id}:campaign",
            str(campaign_id),
        ),
    )

    data_time: datetime | None = None

    if latest_value is not None:
        latest_payload = json.loads(latest_value)
        data_time = _parse_data_time(
            latest_payload["collected_at"]
        )

    now = datetime.now(timezone.utc).replace(
        tzinfo=None
    )

    return CampaignBudgetResult(
        campaign_id=campaign_id,
        data_time=data_time,
        is_stale=(
            not items
            or data_time is None
            or now - data_time
            > timedelta(minutes=10)
        ),
        items=items,
    )
