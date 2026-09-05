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
from app.models import InterventionSuggestion, User
from app.schemas import (
    ApprovalDecisionRequest,
    ApprovalDetail,
    ApprovalRejectRequest,
    ApprovalStatus,
)
from app.services.approval import (
    approve_approval,
    get_approval_detail,
    list_approvals,
    reject_approval,
    submit_suggestion_for_approval,
)
from app.services.campaign import get_campaign


SuggestionId = Annotated[int, Path(gt=0)]
ApprovalId = Annotated[int, Path(gt=0)]
ApprovalApprover = Annotated[
    User,
    Depends(require_role("投放负责人")),
]

router = APIRouter(
    tags=["approvals"],
    route_class=UnifiedResponseRoute,
)


@router.post(
    "/suggestions/{suggestion_id}/submit-approval",
    response_model=None,
)
async def suggestion_submit_approval(
    suggestion_id: SuggestionId,
    session: SessionDep,
    current_user: CurrentUser,
) -> ApprovalDetail:
    """提交干预建议并按风险决定后续流程。

    Args:
        suggestion_id: 待提交的干预建议编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        新建的审批记录及状态更新后的建议。

    Raises:
        HTTPException: 建议不可访问、状态不允许提交，
            或动作超过允许的执行边界。
    """
    suggestion = await session.get(
        InterventionSuggestion,
        suggestion_id,
    )

    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="干预建议不存在",
        )

    campaign = await get_campaign(
        session,
        suggestion.campaign_id,
        current_user,
    )

    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="干预建议不存在",
        )

    try:
        result = await submit_suggestion_for_approval(
            session,
            suggestion.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="干预建议不存在",
        )

    return result


@router.get(
    "/approvals",
    response_model=None,
)
async def approval_list(
    session: SessionDep,
    current_user: CurrentUser,
    status_filter: Annotated[
        ApprovalStatus | None,
        Query(alias="status"),
    ] = None,
) -> list[ApprovalDetail]:
    """查询当前用户可访问的审批列表。

    Args:
        session: 数据库异步会话。
        current_user: 当前登录用户。
        status_filter: 可选的审批状态筛选条件。

    Returns:
        审批记录及关联干预建议列表。
    """
    return await list_approvals(
        session,
        current_user,
        status_filter=status_filter,
    )


@router.get(
    "/approvals/{approval_id}",
    response_model=None,
)
async def approval_detail(
    approval_id: ApprovalId,
    session: SessionDep,
    current_user: CurrentUser,
) -> ApprovalDetail:
    """查询当前用户可访问的审批详情。

    Args:
        approval_id: 审批记录编号。
        session: 数据库异步会话。
        current_user: 当前登录用户。

    Returns:
        审批记录及关联的干预建议。

    Raises:
        HTTPException: 审批不存在或当前用户无权访问时返回 404。
    """
    result = await get_approval_detail(
        session,
        approval_id,
        current_user,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="审批记录不存在",
        )

    return result


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=None,
)
async def approval_approve(
    approval_id: ApprovalId,
    form: ApprovalDecisionRequest,
    session: SessionDep,
    approver: ApprovalApprover,
) -> ApprovalDetail:
    """通过一条待处理审批。

    Args:
        approval_id: 待通过的审批记录编号。
        form: 可选的审批意见。
        session: 数据库异步会话。
        approver: 当前投放负责人。

    Returns:
        更新后的审批记录及关联干预建议。

    Raises:
        HTTPException: 审批不存在或当前状态不能通过。
    """
    try:
        result = await approve_approval(
            session,
            approval_id,
            approver,
            form.opinion,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="审批记录不存在",
        )

    return result


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=None,
)
async def approval_reject(
    approval_id: ApprovalId,
    form: ApprovalRejectRequest,
    session: SessionDep,
    approver: ApprovalApprover,
) -> ApprovalDetail:
    """驳回一条待处理审批。

    Args:
        approval_id: 待驳回的审批记录编号。
        form: 包含必填驳回原因的请求参数。
        session: 数据库异步会话。
        approver: 当前投放负责人。

    Returns:
        更新后的审批记录及关联干预建议。

    Raises:
        HTTPException: 审批不存在、原因无效或状态不能驳回。
    """
    try:
        result = await reject_approval(
            session,
            approval_id,
            approver,
            form.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="审批记录不存在",
        )

    return result
