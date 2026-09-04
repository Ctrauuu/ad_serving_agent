import operator
from collections.abc import Awaitable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, pstdev
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.redis import redis_client
from app.models import (
    AdGroup,
    AdMetricRealtime,
    AdPlan,
    AnomalyRecord,
    Campaign,
    Channel,
    MonitorRule,
    Strategy,
)

from app.schemas import (
    AnomalyScanError,
    AnomalyScanResult,
    AnomalyStatus,
)


async def list_monitor_rules(
    session: AsyncSession,
) -> list[MonitorRule]:
    """查询全部监控规则。

    Args:
        session: 数据库异步会话。

    Returns:
        返回类型为 list[MonitorRule] 的执行结果。
    """
    rules = await session.scalars(
        select(MonitorRule).order_by(
            MonitorRule.id
        )
    )
    return list(rules.all())
    
def get_campaign_stage(
    campaign: Campaign,
    current_date: date | None = None,
) -> str:
    """判断活动投放阶段。

    Args:
        campaign: 活动 ORM 对象。
        current_date: 判断阶段的日期。

    Returns:
        返回类型为 str 的执行结果。
    """
    current_date = current_date or date.today()
    elapsed_days = (
        current_date - campaign.start_date
    ).days
    remaining_days = (
        campaign.end_date - current_date
    ).days

    if elapsed_days < 3:
        return "学习期"

    if remaining_days < 3:
        return "尾期"

    return "稳态期"


def get_metric_value(
    row: AdMetricRealtime,
    metric: str,
) -> Decimal | None:
    """读取或计算指定指标。

    Args:
        row: 指标记录。
        metric: 指标名称。

    Returns:
        返回类型为 Decimal | None 的执行结果。
    """
    if metric == "valid_lead_rate":
        if row.lead == 0:
            return None

        return (
            Decimal(row.valid_lead)
            / Decimal(row.lead)
        ).quantize(Decimal("0.0001"))

    value = getattr(row, metric, None)

    if value is None:
        return None

    return Decimal(str(value))

def calculate_dynamic_baseline(
    values: list[Decimal],
) -> tuple[Decimal, Decimal] | None:
    """计算动态基线均值和标准差。

    Args:
        values: 历史指标序列。

    Returns:
        返回类型为 tuple[Decimal, Decimal] | None 的执行结果。
    """
    if len(values) < 3:
        return None

    return (
        mean(values),
        pstdev(values),
    )

def matches_operator(
    current: Decimal,
    threshold: Decimal,
    symbol: str,
) -> bool:
    """执行规则阈值比较。

    Args:
        current: 当前指标值。
        threshold: 规则阈值。
        symbol: 比较运算符。

    Returns:
        返回类型为 bool 的执行结果。
    """
    operations = {
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
    }

    comparison = operations.get(symbol)

    if comparison is None:
        raise ValueError(
            f"不支持的规则运算符：{symbol}"
        )

    return comparison(current, threshold)


def evaluate_rule(
    rule: MonitorRule,
    current_row: AdMetricRealtime,
    history_rows: list[AdMetricRealtime],
    strategy_targets: dict[str, Decimal],
    daily_budget: Decimal,
    stage: str,
) -> dict[str, Any] | None:
    """判断一条监控规则是否命中异常。

    Args:
        rule: 当前启用的监控规则。
        current_row: 广告组最新小时指标。
        history_rows: 按时间倒序排列的历史小时指标。
        strategy_targets: 已确认策略中的预期指标。
        daily_budget: 当前广告组日预算。
        stage: 活动当前投放阶段。

    Returns:
        命中时返回异常类型、指标值、基线和证据；
        未命中或缺少判断数据时返回 None。
    """
    if (
        rule.stage != "全部"
        and rule.stage != stage
    ):
        return None

    condition = rule.condition_json
    rule_type = rule.rule_type

    if rule_type == "budget_rate":
        current_cost = get_metric_value(
            current_row,
            "cost",
        )
        budget_pct = Decimal(
            str(condition["hourly_budget_pct"])
        )
        threshold = daily_budget * budget_pct

        if stage == "学习期":
            threshold *= Decimal("1.5")

        current_quality = get_metric_value(
            current_row,
            "valid_lead_rate",
        )
        quality_values = [
            value
            for row in history_rows[:3]
            if (
                value := get_metric_value(
                    row,
                    "valid_lead_rate",
                )
            )
            is not None
        ]
        quality_baseline = (
            mean(quality_values)
            if len(quality_values) >= 3
            else strategy_targets.get(
                "valid_lead_rate"
            )
        )

        if (
            current_quality is not None
            and quality_baseline is not None
            and current_quality
            >= quality_baseline
        ):
            return None

        if (
            current_cost is None
            or current_cost <= threshold
        ):
            return None

        return {
            "anomaly_type": "cost_rate_fast",
            "metric_value": current_cost,
            "baseline_value": threshold,
            "evidence": {
                "rule_type": rule_type,
                "stage": stage,
                "hourly_budget_pct": float(
                    budget_pct
                ),
                "current_quality": (
                    float(current_quality)
                    if current_quality is not None
                    else None
                ),
                "quality_baseline": (
                    float(quality_baseline)
                    if quality_baseline is not None
                    else None
                ),
            },
        }

    current_value = get_metric_value(
        current_row,
        rule.metric,
    )

    if current_value is None:
        return None

    if rule_type == "fixed_threshold":
        if condition.get("base") == "target":
            base_value = strategy_targets.get(
                rule.metric
            )

            if base_value is None:
                return None

            threshold = (
                base_value
                * Decimal(
                    str(
                        condition.get(
                            "multiple",
                            1,
                        )
                    )
                )
            )
        else:
            raw_threshold = condition.get(
                "threshold",
                condition.get("value"),
            )

            if raw_threshold is None:
                return None

            threshold = Decimal(
                str(raw_threshold)
            )

        symbol = str(
            condition.get("operator", ">")
        )

        if stage == "学习期":
            threshold *= (
                Decimal("1.5")
                if symbol in {">", ">="}
                else Decimal("0.5")
            )

        if not matches_operator(
            current_value,
            threshold,
            symbol,
        ):
            return None

        return {
            "anomaly_type": (
                f"{rule.metric}_high"
                if symbol in {">", ">="}
                else f"{rule.metric}_low"
            ),
            "metric_value": current_value,
            "baseline_value": threshold,
            "evidence": {
                "rule_type": rule_type,
                "stage": stage,
                "operator": symbol,
                "threshold": float(threshold),
            },
        }

    if rule_type == "dynamic_baseline":
        window_text = str(
            condition.get("window", "3h")
        )

        try:
            window_hours = max(
                int(
                    window_text.removesuffix(
                        "h"
                    )
                ),
                1,
            )
        except ValueError as exc:
            raise ValueError(
                f"无效的基线窗口：{window_text}"
            ) from exc

        history_values = [
            value
            for row in history_rows[
                :window_hours
            ]
            if (
                value := get_metric_value(
                    row,
                    rule.metric,
                )
            )
            is not None
        ]
        baseline = calculate_dynamic_baseline(
            history_values
        )
        deviation: Decimal | None = None

        if baseline is not None:
            baseline_value, deviation = baseline
        else:
            baseline_value = strategy_targets.get(
                rule.metric
            )

            if baseline_value is None:
                return None

        if "drop_pct" in condition:
            change_pct = Decimal(
                str(condition["drop_pct"])
            )
            threshold = (
                baseline_value
                * (Decimal("1") - change_pct)
            )

            if deviation is not None:
                threshold = min(
                    threshold,
                    baseline_value - deviation,
                )

            if stage == "学习期":
                threshold *= Decimal("0.5")

            hit = current_value < threshold
            direction = "drop"
        elif "rise_pct" in condition:
            change_pct = Decimal(
                str(condition["rise_pct"])
            )
            threshold = (
                baseline_value
                * (Decimal("1") + change_pct)
            )

            if deviation is not None:
                threshold = max(
                    threshold,
                    baseline_value + deviation,
                )

            if stage == "学习期":
                threshold *= Decimal("1.5")

            hit = current_value > threshold
            direction = "rise"
        else:
            raise ValueError(
                f"动态规则 {rule.id} 缺少变化比例"
            )

        if not hit:
            return None

        return {
            "anomaly_type": (
                "valid_lead_drop"
                if (
                    rule.metric
                    == "valid_lead_rate"
                    and direction == "drop"
                )
                else (
                    f"{rule.metric}_{direction}"
                )
            ),
            "metric_value": current_value,
            "baseline_value": baseline_value,
            "evidence": {
                "rule_type": rule_type,
                "stage": stage,
                "threshold": float(threshold),
                "deviation": (
                    float(deviation)
                    if deviation is not None
                    else None
                ),
                "history_points": len(
                    history_values
                ),
            },
        }

    if rule_type in {"yoy", "mom"}:
        comparison_row: (
            AdMetricRealtime | None
        ) = None

        if rule_type == "mom":
            if history_rows:
                comparison_row = history_rows[0]
        else:
            expected_time = (
                current_row.window_start
                - timedelta(days=1)
            )
            candidates = [
                row
                for row in history_rows
                if abs(
                    (
                        row.window_start
                        - expected_time
                    ).total_seconds()
                )
                <= 3600
            ]

            if candidates:
                comparison_row = min(
                    candidates,
                    key=lambda row: abs(
                        (
                            row.window_start
                            - expected_time
                        ).total_seconds()
                    ),
                )

        if comparison_row is None:
            return None

        baseline_value = get_metric_value(
            comparison_row,
            rule.metric,
        )

        if baseline_value is None:
            return None

        if "rise_pct" in condition:
            change_pct = Decimal(
                str(condition["rise_pct"])
            )
            threshold = (
                baseline_value
                * (Decimal("1") + change_pct)
            )

            if stage == "学习期":
                threshold *= Decimal("1.5")

            hit = current_value > threshold
            direction = "rise"
        elif "drop_pct" in condition:
            change_pct = Decimal(
                str(condition["drop_pct"])
            )
            threshold = (
                baseline_value
                * (Decimal("1") - change_pct)
            )

            if stage == "学习期":
                threshold *= Decimal("0.5")

            hit = current_value < threshold
            direction = "drop"
        else:
            raise ValueError(
                f"对比规则 {rule.id} 缺少变化比例"
            )

        if not hit:
            return None

        return {
            "anomaly_type": (
                f"{rule.metric}_"
                f"{rule_type}_{direction}"
            ),
            "metric_value": current_value,
            "baseline_value": baseline_value,
            "evidence": {
                "rule_type": rule_type,
                "stage": stage,
                "threshold": float(threshold),
                "comparison_time": (
                    comparison_row
                    .window_start
                    .isoformat()
                ),
            },
        }

    raise ValueError(
        f"不支持的规则类型：{rule_type}"
    )


async def scan_campaign_anomalies(
    session: AsyncSession,
    campaign: Campaign,
) -> AnomalyScanResult:
    """扫描活动指标并创建去重后的异常记录。

    Args:
        session: 数据库异步会话。
        campaign: 当前待扫描的活动。

    Returns:
        本次扫描阶段、处理数量、异常编号及规则错误。
    """
    rules = list(
        (
            await session.scalars(
                select(MonitorRule)
                .where(MonitorRule.enabled.is_(True))
                .order_by(MonitorRule.id)
            )
        ).all()
    )

    if not rules:
        raise ValueError("没有启用的监控规则")

    strategy = await session.scalar(
        select(Strategy)
        .where(
            Strategy.campaign_id == campaign.id,
            Strategy.status == "已确认",
        )
        .order_by(Strategy.version.desc())
    )
    strategy_targets: dict[str, Decimal] = {}

    if strategy and strategy.expected_metrics:
        strategy_targets = {
            key: Decimal(str(value))
            for key, value
            in strategy.expected_metrics.items()
        }

    task_rows = (
        await session.execute(
            select(AdGroup, AdPlan, Channel)
            .join(
                AdPlan,
                AdGroup.ad_plan_id == AdPlan.id,
            )
            .join(
                Channel,
                Channel.id == AdPlan.channel_id,
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

    group_ids = [
        group.id
        for group, _, _ in task_rows
    ]
    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    metric_rows = list(
        (
            await session.scalars(
                select(AdMetricRealtime)
                .where(
                    AdMetricRealtime.campaign_id
                    == campaign.id,
                    AdMetricRealtime.dimension
                    == "ad_group",
                    AdMetricRealtime.time_window
                    == "hour",
                    AdMetricRealtime.dim_id.in_(
                        group_ids
                    ),
                    AdMetricRealtime.window_start
                    >= now - timedelta(days=8),
                )
                .order_by(
                    AdMetricRealtime.dim_id,
                    AdMetricRealtime.window_start.desc(),
                )
            )
        ).all()
    )

    metrics_by_group: dict[
        int,
        list[AdMetricRealtime],
    ] = {}

    for metric_row in metric_rows:
        metrics_by_group.setdefault(
            metric_row.dim_id,
            [],
        ).append(metric_row)

    stage = get_campaign_stage(campaign)
    evaluated_rules = 0
    deduplicated_count = 0
    skipped_stale_groups = 0
    skipped_no_data_groups = 0
    created_ids: list[int] = []
    errors: list[AnomalyScanError] = []
    acquired_keys: list[str] = []

    try:
        for group, plan, channel in task_rows:
            group_metrics = metrics_by_group.get(
                group.id,
                [],
            )

            if not group_metrics:
                skipped_no_data_groups += 1
                continue

            current_row = group_metrics[0]
            history_rows = group_metrics[1:]

            if (
                now - current_row.collected_at
                > timedelta(minutes=10)
            ):
                skipped_stale_groups += 1
                continue

            for rule in rules:
                if rule.channel_scope:
                    scopes = {
                        value.strip()
                        for value
                        in rule.channel_scope.split(",")
                        if value.strip()
                    }

                    if (
                        channel.name not in scopes
                        and str(channel.id) not in scopes
                    ):
                        continue

                evaluated_rules += 1

                try:
                    match = evaluate_rule(
                        rule=rule,
                        current_row=current_row,
                        history_rows=history_rows,
                        strategy_targets=(
                            strategy_targets
                        ),
                        daily_budget=(
                            group.budget_daily
                        ),
                        stage=stage,
                    )
                except ValueError as exc:
                    errors.append(
                        AnomalyScanError(
                            rule_id=rule.id,
                            target_id=group.id,
                            message=str(exc),
                        )
                    )
                    continue

                if match is None:
                    continue

                anomaly_type = str(
                    match["anomaly_type"]
                )
                dedup_key = (
                    f"anomaly:dedup:"
                    f"{campaign.id}:"
                    f"ad_group:{group.id}:"
                    f"{anomaly_type}"
                )
                acquired = await cast(
                    Awaitable[bool | None],
                    redis_client.set(
                        dedup_key,
                        "1",
                        ex=600,
                        nx=True,
                    ),
                )

                if not acquired:
                    deduplicated_count += 1
                    continue

                acquired_keys.append(dedup_key)
                evidence = dict(
                    match["evidence"]
                )
                evidence.update(
                    {
                        "rule_name": rule.name,
                        "channel_id": channel.id,
                        "channel_name": channel.name,
                        "window_start": (
                            current_row
                            .window_start
                            .isoformat()
                        ),
                        "collected_at": (
                            current_row
                            .collected_at
                            .isoformat()
                        ),
                    }
                )

                metric_value = Decimal(
                    str(match["metric_value"])
                ).quantize(
                    Decimal("0.0001")
                )
                baseline_raw = match[
                    "baseline_value"
                ]
                baseline_value = (
                    Decimal(
                        str(baseline_raw)
                    ).quantize(
                        Decimal("0.0001")
                    )
                    if baseline_raw is not None
                    else None
                )

                record = AnomalyRecord(
                    campaign_id=campaign.id,
                    target_type="ad_group",
                    target_id=group.id,
                    anomaly_type=anomaly_type,
                    metric=rule.metric,
                    metric_value=metric_value,
                    baseline_value=baseline_value,
                    rule_id=rule.id,
                    severity=rule.risk_level,
                    evidence_json=evidence,
                    status="待归因",
                    detected_at=now,
                )
                session.add(record)
                await session.flush()
                created_ids.append(record.id)

        await session.commit()

    except Exception:
        await session.rollback()

        if acquired_keys:
            await cast(
                Awaitable[int],
                redis_client.delete(
                    *acquired_keys
                ),
            )

        raise


    return AnomalyScanResult(
        campaign_id=campaign.id,
        status=(
            "partial"
            if errors
            else "completed"
        ),
        stage=stage,
        scanned_groups=len(task_rows),
        evaluated_rules=evaluated_rules,
        created_count=len(created_ids),
        deduplicated_count=deduplicated_count,
        skipped_stale_groups=(
            skipped_stale_groups
        ),
        skipped_no_data_groups=(
            skipped_no_data_groups
        ),
        created_ids=created_ids,
        errors=errors,
    )


async def list_campaign_anomalies(
    session: AsyncSession,
    campaign_id: int,
    status_filter: AnomalyStatus | None = None,
) -> list[AnomalyRecord]:
    """查询活动异常记录并支持状态筛选。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。
        status_filter: 可选的异常处理状态。

    Returns:
        按发现时间倒序排列的异常记录。
    """
    statement = select(AnomalyRecord).where(
        AnomalyRecord.campaign_id
        == campaign_id
    )

    if status_filter is not None:
        statement = statement.where(
            AnomalyRecord.status
            == status_filter
        )

    records = await session.scalars(
        statement.order_by(
            AnomalyRecord.detected_at.desc(),
            AnomalyRecord.id.desc(),
        )
    )

    return list(records.all())
