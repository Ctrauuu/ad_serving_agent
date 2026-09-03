import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.infrastructure.database import async_session
from app.models import AdGroup, Campaign
from app.services.metric import sync_campaign_metrics


logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def sync_active_campaign_metrics() -> None:
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

        except ValueError as exc:
            logger.info(
                "活动 %s 暂未同步指标：%s",
                campaign_id,
                exc,
            )
        except Exception:
            logger.exception(
                "活动 %s 指标同步失败",
                campaign_id,
            )


def start_metric_scheduler() -> None:
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
    if scheduler.running:
        scheduler.shutdown(wait=False)