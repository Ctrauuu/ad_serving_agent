from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    status,
)

from app.api.dependencies.auth import (
    CurrentUser,
    SessionDep,
)
from app.api.routing import UnifiedResponseRoute
from app.models import AdPlan
from app.schemas import AdTaskStatusResult
from app.services.ad_task import (
    sync_ad_task_status,
)
from app.services.campaign import get_campaign


TaskId = Annotated[int, Path(gt=0)]

router = APIRouter(
    prefix="/ad-tasks",
    tags=["ad-tasks"],
    route_class=UnifiedResponseRoute,
)

@router.get(
    "/{task_id}/status",
    response_model=None,
)
async def ad_task_status(
    task_id: TaskId,
    session: SessionDep,
    current_user: CurrentUser,
) -> AdTaskStatusResult:
    """同步并返回广告任务状态。

    Args:
        task_id: 广告任务编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        返回类型为 AdTaskStatusResult 的执行结果。
    """
    plan = await session.get(
        AdPlan,
        task_id,
    )

    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="广告任务不存在",
        )

    campaign = await get_campaign(
        session,
        plan.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="广告任务不存在",
        )

    return await sync_ad_task_status(
        session=session,
        campaign=campaign,
        plan=plan,
    )
