import asyncio

import pytest

from app.tasks.scheduler import (
    scheduler,
    start_metric_scheduler,
    stop_metric_scheduler,
)


@pytest.mark.asyncio
async def test_metric_scheduler_registers_one_five_minute_job() -> None:
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
