from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    status,
)

from app.api.dependencies.auth import (
    CurrentUser,
    SessionDep,
    require_role,
)
from app.api.routing import UnifiedResponseRoute
from app.models import ActionExecution, User
from app.schemas import ActionExecutionRead
from app.services.action import (
    list_action_executions,
    rollback_action,
)
from app.services.campaign import get_campaign


CampaignIdQuery = Annotated[int, Query(gt=0)]
ActionId = Annotated[int, Path(gt=0)]
ActionRollbacker = Annotated[
    User,
    Depends(require_role("投放负责人")),
]

router = APIRouter(
    tags=["actions"],
    route_class=UnifiedResponseRoute,
)


@router.get(
    "/actions",
    response_model=None,
)
async def action_list(
    campaign_id: CampaignIdQuery,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[ActionExecutionRead]:
    """查询指定活动的动作执行记录。

    Args:
        campaign_id: 要查询的活动编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        当前活动的动作执行记录列表。

    Raises:
        HTTPException: 活动不存在或当前用户无权访问。
    """
    campaign = await get_campaign(
        session,
        campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="活动不存在",
        )

    records = await list_action_executions(
        session,
        campaign.id,
    )

    return [
        ActionExecutionRead.model_validate(record)
        for record in records
    ]


@router.get(
    "/actions/{action_id}",
    response_model=None,
)
async def action_detail(
    action_id: ActionId,
    session: SessionDep,
    current_user: CurrentUser,
) -> ActionExecutionRead:
    """查询一条动作执行记录的完整详情。

    Args:
        action_id: 动作执行记录编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        包含前后快照、工具结果和回滚状态的执行记录。

    Raises:
        HTTPException: 执行记录不存在或当前用户无权访问。
    """
    action = await session.get(
        ActionExecution,
        action_id,
    )

    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="动作执行记录不存在",
        )

    campaign = await get_campaign(
        session,
        action.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="动作执行记录不存在",
        )

    return ActionExecutionRead.model_validate(
        action
    )


@router.post(
    "/actions/{action_id}/rollback",
    response_model=None,
)
async def action_rollback(
    action_id: ActionId,
    session: SessionDep,
    approver: ActionRollbacker,
) -> ActionExecutionRead:
    """回滚一条已成功执行的广告平台动作。

    Args:
        action_id: 要回滚的动作执行记录编号。
        session: 数据库异步会话。
        approver: 当前投放负责人。

    Returns:
        更新后的动作执行记录及回滚状态。

    Raises:
        HTTPException: 记录不存在、无权访问或不能安全回滚。
    """
    action = await session.get(
        ActionExecution,
        action_id,
    )

    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="动作执行记录不存在",
        )

    campaign = await get_campaign(
        session,
        action.campaign_id,
        approver,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="动作执行记录不存在",
        )

    try:
        result = await rollback_action(
            session,
            action_id,
            approver,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="动作执行记录不存在",
        )

    return ActionExecutionRead.model_validate(
        result
    )
