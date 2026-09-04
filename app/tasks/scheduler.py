import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.infrastructure.database import async_session
from app.models import AdGroup, Campaign
from app.services.anomaly import scan_campaign_anomalies
from app.services.metric import sync_campaign_metrics


logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def sync_active_campaign_metrics() -> None:
    """同步投放中活动指标并执行异常扫描。

    Returns:
        无返回值。
    """
    async with async_session() as session:
        campaign_ids = list(
            (
                await session.scalars(
                    select(Campaign.id)
                    .join(
                        AdGroup,
                        AdGroup.campaign_id
                        == Campaign.id,
                    )
                    .where(
                        Campaign.status == "投放中",
                        AdGroup.status == "已上线",
                    )
                    .distinct()
                )
            ).all()
        )

    for campaign_id in campaign_ids:
        try:
            async with async_session() as session:
                campaign = await session.get(
                    Campaign,
                    campaign_id,
                )

                if campaign is None:
                    continue

                await sync_campaign_metrics(
                    session,
                    campaign,
                )
                await scan_campaign_anomalies(
                    session,
                    campaign,
                )

        except ValueError as exc:
            logger.info(
                "活动 %s 暂未完成监控：%s",
                campaign_id,
                exc,
            )
        except Exception:
            logger.exception(
                "活动 %s 指标同步或异常扫描失败",
                campaign_id,
            )


def start_metric_scheduler() -> None:
    """启动五分钟指标调度任务。

    Returns:
        无返回值。
    """
    if scheduler.running:
        return

    scheduler.add_job(
        sync_active_campaign_metrics,
        trigger="interval",
        minutes=5,
        id="sync_active_campaign_metrics",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.start()


def stop_metric_scheduler() -> None:
    """停止指标调度器。

    Returns:
        无返回值。
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
