import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.infrastructure.database import async_session
from app.models import AdGroup, Campaign
from app.services.anomaly import scan_campaign_anomalies
from app.services.approval import expire_pending_approvals
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


async def scan_expired_approvals() -> list[int]:
    """扫描并标记超过 72 小时的待审批记录。

    Returns:
        本次被标记为已超时的审批记录编号列表。
        扫描失败时记录错误并返回空列表。
    """
    try:
        async with async_session() as session:
            expired_ids = (
                await expire_pending_approvals(
                    session
                )
            )
    except Exception:
        logger.exception("审批超时扫描失败")
        return []

    if expired_ids:
        logger.info(
            "审批超时扫描完成：expired_ids=%s",
            expired_ids,
        )

    return expired_ids


def start_metric_scheduler() -> None:
    """启动指标同步与审批超时调度任务。

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
    scheduler.add_job(
        scan_expired_approvals,
        trigger="interval",
        hours=1,
        id="scan_expired_approvals",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()


def stop_metric_scheduler() -> None:
    """停止指标调度器。

    Returns:
        无返回值。
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
