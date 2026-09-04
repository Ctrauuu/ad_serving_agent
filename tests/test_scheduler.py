import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.tasks.scheduler as scheduler_module
from app.models import Campaign
from app.tasks.scheduler import (
    scheduler,
    start_metric_scheduler,
    stop_metric_scheduler,
    sync_active_campaign_metrics,
)


@pytest.mark.asyncio
async def test_metric_scheduler_registers_one_five_minute_job() -> None:
    """验证调度器仅注册一个五分钟周期任务。"""
    try:
        start_metric_scheduler()
        start_metric_scheduler()

        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "sync_active_campaign_metrics"
        assert jobs[0].trigger.interval.total_seconds() == 300
        assert jobs[0].max_instances == 1
        assert jobs[0].coalesce is True
    finally:
        stop_metric_scheduler()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_scheduler_syncs_metrics_before_scanning_anomalies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证每个投放中活动先同步指标，再执行异常扫描。"""
    list_session = AsyncMock()
    campaign_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [8]
    list_session.scalars.return_value = scalar_result

    campaign = Campaign(id=8, status="投放中")
    campaign_session.get.return_value = campaign
    sessions = [list_session, campaign_session]

    @asynccontextmanager
    async def fake_async_session():
        """按调用顺序返回测试数据库会话。"""
        yield sessions.pop(0)

    calls: list[str] = []

    async def fake_sync(*args: object) -> None:
        """记录指标同步调用。"""
        calls.append("sync")

    async def fake_scan(*args: object) -> None:
        """记录异常扫描调用。"""
        calls.append("scan")

    monkeypatch.setattr(
        scheduler_module,
        "async_session",
        fake_async_session,
    )
    monkeypatch.setattr(
        scheduler_module,
        "sync_campaign_metrics",
        fake_sync,
    )
    monkeypatch.setattr(
        scheduler_module,
        "scan_campaign_anomalies",
        fake_scan,
    )

    await sync_active_campaign_metrics()

    assert calls == ["sync", "scan"]
