import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdMetricRealtime
from app.services.metric import (
    _save_metric,
    get_campaign_budget,
    get_metric_trend,
    get_realtime_metrics,
)


@pytest.mark.asyncio
async def test_save_metric_calculates_derived_values() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    data_time = datetime(2026, 9, 3, 13, 30)

    row = await _save_metric(
        session,
        8,
        ("campaign", 8, "minute", data_time),
        {
            "impression": 1000,
            "click": 100,
            "cost": Decimal("200"),
            "lead": 20,
            "valid_lead": 10,
            "order": 2,
            "revenue": Decimal("600"),
            "data_time": data_time,
        },
    )

    assert row.ctr == Decimal("0.100000")
    assert row.cpc == Decimal("2.00")
    assert row.cpa == Decimal("10.00")
    assert row.roi == Decimal("3.0000")
    session.add.assert_called_once_with(row)


@pytest.mark.asyncio
async def test_realtime_metrics_recalculates_stale_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collected_at = (
        datetime.now(timezone.utc)
        - timedelta(minutes=11)
    ).replace(tzinfo=None)
    hvals = AsyncMock(
        return_value=[
            json.dumps(
                {
                    "dimension": "campaign",
                    "dim_id": 8,
                    "time_window": "minute",
                    "window_start": collected_at.isoformat(),
                    "impression": 100,
                    "click": 10,
                    "cost": 20,
                    "lead": 2,
                    "valid_lead": 1,
                    "order": 0,
                    "ctr": 0.1,
                    "cpc": 2,
                    "cpa": 10,
                    "roi": 0,
                    "collected_at": collected_at.isoformat(),
                    "is_stale": False,
                }
            )
        ]
    )
    monkeypatch.setattr(
        "app.services.metric.redis_client.hvals",
        hvals,
    )

    result = await get_realtime_metrics(
        8,
        "campaign",
    )

    assert result.is_stale is True
    assert result.items[0].is_stale is True


@pytest.mark.asyncio
async def test_metric_trend_groups_rows_by_dimension() -> None:
    session = AsyncMock(spec=AsyncSession)
    rows = MagicMock()
    rows.all.return_value = [
        AdMetricRealtime(
            campaign_id=8,
            dimension="channel",
            dim_id=2,
            time_window="hour",
            window_start=datetime(2026, 9, 3, 13),
            impression=100,
            click=10,
            cost=Decimal("20"),
            lead=2,
            valid_lead=1,
            order=0,
            ctr=Decimal("0.1"),
            cpc=Decimal("2"),
            cpa=Decimal("10"),
            roi=Decimal("0"),
            collected_at=datetime(2026, 9, 3, 13),
        )
    ]
    session.scalars.return_value = rows

    result = await get_metric_trend(
        session,
        8,
        "channel",
        "hour",
    )

    assert len(result.series) == 1
    assert result.series[0].dim_id == 2
    assert result.series[0].points[0].click == 10


def test_metric_trend_supports_all_aggregated_windows() -> None:
    from typing import get_args

    from app.schemas import MetricTrendWindow

    assert set(get_args(MetricTrendWindow)) == {
        "minute",
        "hour",
        "day",
    }


@pytest.mark.asyncio
async def test_campaign_budget_orders_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collected_at = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)
    budget_values = [
        json.dumps(
            {
                "target_type": target_type,
                "target_id": target_id,
                "budget_total": 1000,
                "cost_total": 100,
                "cost_rate": 10,
                "remaining": 900,
                "alert_status": "正常",
            }
        )
        for target_type, target_id in [
            ("ad_group", 3),
            ("campaign", 8),
            ("ad_plan", 2),
        ]
    ]
    monkeypatch.setattr(
        "app.services.metric.redis_client.hvals",
        AsyncMock(return_value=budget_values),
    )
    monkeypatch.setattr(
        "app.services.metric.redis_client.hget",
        AsyncMock(
            return_value=json.dumps(
                {
                    "collected_at": (
                        collected_at.isoformat()
                    )
                }
            )
        ),
    )

    result = await get_campaign_budget(8)

    assert result.is_stale is False
    assert [item.target_type for item in result.items] == [
        "campaign",
        "ad_plan",
        "ad_group",
    ]
