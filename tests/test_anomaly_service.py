from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.anomaly import (
    calculate_dynamic_baseline,
    get_campaign_stage,
    get_metric_value,
    matches_operator,
    evaluate_rule,
    list_campaign_anomalies,
    scan_campaign_anomalies,
)


def test_anomaly_rule_helpers() -> None:
    campaign = Campaign(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )
    metric = AdMetricRealtime(
        lead=10,
        valid_lead=4,
        cpa=Decimal("120"),
    )

    assert get_campaign_stage(
        campaign,
        date(2026, 9, 2),
    ) == "学习期"
    assert get_campaign_stage(
        campaign,
        date(2026, 9, 15),
    ) == "稳态期"
    assert get_campaign_stage(
        campaign,
        date(2026, 9, 29),
    ) == "尾期"
    assert get_metric_value(
        metric,
        "valid_lead_rate",
    ) == Decimal("0.4000")
    assert calculate_dynamic_baseline(
        [Decimal("1"), Decimal("2"), Decimal("3")]
    ) == (Decimal("2"), Decimal("0.8164965809277260327324280249"))
    assert matches_operator(
        Decimal("2"),
        Decimal("1"),
        ">",
    ) is True

    with pytest.raises(ValueError, match="不支持"):
        matches_operator(
            Decimal("2"),
            Decimal("1"),
            "=",
        )


def test_evaluate_rule_covers_core_rule_types() -> None:
    current = AdMetricRealtime(
        window_start=date(2026, 9, 4),
        cost=Decimal("200"),
        cpa=Decimal("500"),
        lead=10,
        valid_lead=1,
    )
    history = [
        AdMetricRealtime(
            window_start=date(2026, 9, day),
            cpa=Decimal("100"),
            lead=10,
            valid_lead=4,
        )
        for day in (3, 2, 1)
    ]
    targets = {
        "cpa": Decimal("260"),
        "valid_lead_rate": Decimal("0.42"),
    }

    fixed = MonitorRule(
        id=1,
        rule_type="fixed_threshold",
        metric="cpa",
        condition_json={
            "base": "target",
            "multiple": 1.5,
            "operator": ">",
        },
        stage="稳态期",
    )
    budget = MonitorRule(
        id=3,
        rule_type="budget_rate",
        metric="cost_rate",
        condition_json={
            "hourly_budget_pct": 0.15,
        },
        stage="全部",
    )
    yoy = MonitorRule(
        id=4,
        rule_type="yoy",
        metric="cpa",
        condition_json={"rise_pct": 0.5},
        stage="稳态期",
    )

    assert evaluate_rule(
        fixed,
        current,
        history,
        targets,
        Decimal("1000"),
        "稳态期",
    )["anomaly_type"] == "cpa_high"
    assert evaluate_rule(
        budget,
        current,
        history,
        targets,
        Decimal("1000"),
        "稳态期",
    )["anomaly_type"] == "cost_rate_fast"
    assert evaluate_rule(
        yoy,
        current,
        history,
        targets,
        Decimal("1000"),
        "稳态期",
    )["anomaly_type"] == "cpa_yoy_rise"

    current.valid_lead = 5
    assert evaluate_rule(
        budget,
        current,
        history,
        targets,
        Decimal("1000"),
        "稳态期",
    ) is None


@pytest.mark.asyncio
async def test_scan_creates_quantized_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    today = date.today()
    campaign = Campaign(
        id=8,
        start_date=today - timedelta(days=5),
        end_date=today + timedelta(days=10),
    )
    rule = MonitorRule(
        id=1,
        name="CPA过高",
        rule_type="fixed_threshold",
        metric="cpa",
        condition_json={
            "base": "target",
            "multiple": 1.5,
            "operator": ">",
        },
        stage="稳态期",
        risk_level="高",
        enabled=True,
    )
    strategy = Strategy(
        expected_metrics={"cpa": 100},
        status="已确认",
        version=1,
    )
    group = AdGroup(
        id=32,
        campaign_id=8,
        status="已上线",
        budget_daily=Decimal("1000"),
    )
    plan = AdPlan(
        id=4,
        campaign_id=8,
        status="已上线",
        channel_id=1,
    )
    channel = Channel(id=1, name="信息流")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    metric = AdMetricRealtime(
        campaign_id=8,
        dimension="ad_group",
        dim_id=32,
        time_window="hour",
        window_start=now.replace(minute=0, second=0, microsecond=0),
        collected_at=now,
        cpa=Decimal("200"),
        cost=Decimal("100"),
        lead=10,
        valid_lead=1,
    )

    rule_rows = MagicMock()
    rule_rows.all.return_value = [rule]
    metric_rows = MagicMock()
    metric_rows.all.return_value = [metric]
    session.scalars.side_effect = [rule_rows, metric_rows]
    session.scalar.return_value = strategy
    task_rows = MagicMock()
    task_rows.all.return_value = [(group, plan, channel)]
    session.execute.return_value = task_rows
    session.add.side_effect = lambda record: setattr(record, "id", 99)
    monkeypatch.setattr(
        "app.services.anomaly.redis_client.set",
        AsyncMock(return_value=True),
    )

    result = await scan_campaign_anomalies(
        session,
        campaign,
    )

    record = session.add.call_args.args[0]
    assert isinstance(record, AnomalyRecord)
    assert record.metric_value == Decimal("200.0000")
    assert record.baseline_value == Decimal("150.0000")
    assert result.created_ids == [99]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_campaign_anomalies_returns_query_result() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    expected = [AnomalyRecord(id=2), AnomalyRecord(id=1)]
    result.all.return_value = expected
    session.scalars.return_value = result

    records = await list_campaign_anomalies(
        session,
        8,
        "待归因",
    )

    assert records == expected
    session.scalars.assert_awaited_once()
