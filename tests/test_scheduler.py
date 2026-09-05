import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.tasks.scheduler as scheduler_module
from app.models import Campaign
from app.tasks.scheduler import (
    scan_expired_approvals,
    scheduler,
    start_metric_scheduler,
    stop_metric_scheduler,
    sync_active_campaign_metrics,
)


@pytest.mark.asyncio
async def test_scheduler_registers_metric_and_approval_jobs() -> None:
    """验证调度器幂等注册指标和审批超时任务。"""
    try:
        start_metric_scheduler()
        start_metric_scheduler()

        jobs = {
            job.id: job
            for job in scheduler.get_jobs()
        }
        assert set(jobs) == {
            "sync_active_campaign_metrics",
            "scan_expired_approvals",
        }
        metric_job = jobs["sync_active_campaign_metrics"]
        approval_job = jobs["scan_expired_approvals"]
        assert metric_job.trigger.interval.total_seconds() == 300
        assert approval_job.trigger.interval.total_seconds() == 3600
        assert metric_job.max_instances == 1
        assert approval_job.max_instances == 1
        assert metric_job.coalesce is True
        assert approval_job.coalesce is True
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


@pytest.mark.asyncio
async def test_scheduler_scans_expired_approvals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批超时任务创建会话并返回超时编号。"""
    session = AsyncMock()

    @asynccontextmanager
    async def fake_async_session():
        """提供审批超时扫描使用的测试数据库会话。"""
        yield session

    expire_service = AsyncMock(return_value=[10, 11])
    monkeypatch.setattr(
        scheduler_module,
        "async_session",
        fake_async_session,
    )
    monkeypatch.setattr(
        scheduler_module,
        "expire_pending_approvals",
        expire_service,
    )

    expired_ids = await scan_expired_approvals()

    assert expired_ids == [10, 11]
    expire_service.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_scheduler_isolates_approval_scan_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批扫描失败不会中断后续调度。"""
    session = AsyncMock()

    @asynccontextmanager
    async def fake_async_session():
        """提供审批超时扫描使用的测试数据库会话。"""
        yield session

    monkeypatch.setattr(
        scheduler_module,
        "async_session",
        fake_async_session,
    )
    monkeypatch.setattr(
        scheduler_module,
        "expire_pending_approvals",
        AsyncMock(side_effect=RuntimeError("数据库不可用")),
    )

    expired_ids = await scan_expired_approvals()

    assert expired_ids == []
