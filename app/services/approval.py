import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import (
    ApprovalWorkflowState,
    build_approval_thread_id,
    resume_approval_workflow,
    start_approval_workflow,
)
from app.infrastructure.redis import redis_client
from app.models import (
    ApprovalRecord,
    Campaign,
    InterventionSuggestion,
    User,
)
from app.schemas import (
    ApprovalDetail,
    ApprovalRecordRead,
    ApprovalRoute,
    ApprovalStatus,
    InterventionSuggestionRead,
)


logger = logging.getLogger(__name__)

_APPROVAL_SESSION_TTL_SECONDS = 72 * 60 * 60

def _read_percent(
    params: dict[str, object],
    keys: tuple[str, ...],
) -> Decimal | None:
    """从动作参数中读取百分比。

    Args:
        params: 干预建议的动作参数。
        keys: 按优先级尝试读取的参数名。

    Returns:
        百分比绝对值；参数缺失或格式错误时返回 None。
    """
    value = next(
        (
            params[key]
            for key in keys
            if params.get(key) is not None
        ),
        None,
    )

    if value is None:
        return None

    try:
        return abs(
            Decimal(
                str(value).strip().removesuffix("%")
            )
        )
    except InvalidOperation:
        return None


def decide_approval_route(
    suggestion: InterventionSuggestion,
) -> ApprovalRoute:
    """决定干预建议自动执行、人工审批或禁止执行。

    Args:
        suggestion: 已生成且尚未提交的干预建议。

    Returns:
        auto_execute、requires_approval 或 forbidden。
    """
    action = suggestion.action_type
    params = suggestion.action_params or {}
    scope = params.get("scope")

    if (
        action == "stop_campaign"
        or (
            action == "pause"
            and (
                suggestion.target_type == "campaign"
                or scope == "campaign"
            )
        )
    ):
        return "forbidden"

    if action == "adjust_budget":
        increase_pct = _read_percent(
            params,
            (
                "increase_pct",
                "budget_increase_pct",
            ),
        )
        change_pct = _read_percent(
            params,
            ("change_pct",),
        )
        direction = params.get("direction")

        increases_over_limit = (
            increase_pct is not None
            and increase_pct > Decimal("20")
        ) or (
            direction == "increase"
            and change_pct is not None
            and change_pct > Decimal("20")
        )

        if (
            scope == "campaign"
            and increases_over_limit
        ):
            return "forbidden"

        return "requires_approval"

    if action in {
        "pause",
        "adjust_bid",
        "switch_channel",
    }:
        return "requires_approval"

    if suggestion.risk_level == "高":
        return "requires_approval"

    if action in {
        "extend_observation",
        "manual_review",
    }:
        return "auto_execute"

    if action == "replace_creative":
        creative_ids = params.get("creative_ids")
        has_single_creative = (
            params.get("creative_id") is not None
            or params.get("new_creative_id") is not None
            or (
                isinstance(creative_ids, list)
                and len(creative_ids) == 1
            )
        )

        return (
            "auto_execute"
            if has_single_creative
            else "requires_approval"
        )

    if action == "narrow_audience":
        narrow_pct = _read_percent(
            params,
            (
                "narrow_pct",
                "change_pct",
            ),
        )

        if (
            narrow_pct is not None
            and Decimal("0")
            < narrow_pct
            <= Decimal("10")
        ):
            return "auto_execute"

        return "requires_approval"

    return "forbidden"


def _approval_session_key(
    approval_id: int,
) -> str:
    """生成 Redis 审批会话 Key。

    Args:
        approval_id: 审批记录编号。

    Returns:
        带审批命名空间的 Redis Key。
    """
    return f"approval:session:{approval_id}"


async def create_approval_session(
    approval: ApprovalRecord,
) -> dict[str, object]:
    """创建等待人工决策的 Redis 审批会话。

    Args:
        approval: 已写入 MySQL 并获得主键的审批记录。

    Returns:
        已写入 Redis 的审批会话内容。
    """
    payload: dict[str, object] = {
        "approval_id": approval.id,
        "suggestion_id": approval.suggestion_id,
        "campaign_id": approval.campaign_id,
        "thread_id": build_approval_thread_id(
            approval.campaign_id,
            approval.id,
        ),
        "status": "待审批",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    await redis_client.set(
        _approval_session_key(approval.id),
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        ex=_APPROVAL_SESSION_TTL_SECONDS,
    )

    return payload


async def get_approval_session(
    approval_id: int,
) -> dict[str, object] | None:
    """读取尚未超时的 Redis 审批会话。

    Args:
        approval_id: 审批记录编号。

    Returns:
        审批会话；会话不存在或已过期时返回 None。
    """
    value = await redis_client.get(
        _approval_session_key(approval_id)
    )

    if value is None:
        return None

    payload = json.loads(value)

    if not isinstance(payload, dict):
        return None

    return payload


async def delete_approval_session(
    approval_id: int,
) -> None:
    """删除已通过或已驳回的 Redis 审批会话。

    Args:
        approval_id: 已完成决策的审批记录编号。

    Returns:
        无返回值。
    """
    await redis_client.delete(
        _approval_session_key(approval_id)
    )


async def submit_suggestion_for_approval(
    session: AsyncSession,
    suggestion_id: int,
) -> ApprovalDetail | None:
    """按风险路线提交干预建议。

    Args:
        session: 数据库异步会话。
        suggestion_id: 待提交的干预建议编号。

    Returns:
        审批记录及关联建议；建议不存在时返回 None。

    Raises:
        ValueError: 建议状态不允许提交或动作禁止执行。
        RuntimeError: Redis 审批会话创建失败。
    """
    suggestion = await session.get(
        InterventionSuggestion,
        suggestion_id,
    )

    if suggestion is None:
        return None

    if suggestion.status != "待提交":
        raise ValueError(
            "当前建议状态不允许重复提交审批"
        )

    route = decide_approval_route(suggestion)

    if route == "forbidden":
        raise ValueError(
            "该动作超出 AI 允许的执行边界，"
            "禁止提交执行"
        )

    auto_execute = route == "auto_execute"
    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    approval = ApprovalRecord(
        suggestion_id=suggestion.id,
        campaign_id=suggestion.campaign_id,
        risk_level=suggestion.risk_level,
        auto_execute=auto_execute,
        approval_opinion=(
            "符合自动执行安全边界"
            if auto_execute
            else None
        ),
        status=(
            "已通过"
            if auto_execute
            else "待审批"
        ),
        approved_at=(
            now
            if auto_execute
            else None
        ),
    )

    redis_session_created = False

    try:
        session.add(approval)

        suggestion.status = (
            "待执行"
            if auto_execute
            else "审批中"
        )

        await session.flush()

        if not auto_execute:
            redis_session_created = True

            await create_approval_session(
                approval
            )

            workflow_state: ApprovalWorkflowState = {
                "approval_id": approval.id,
                "suggestion_id": suggestion.id,
                "campaign_id": suggestion.campaign_id,
                "action_type": suggestion.action_type,
                "action_params": (
                    suggestion.action_params or {}
                ),
                "risk_level": suggestion.risk_level,
                "decision": "pending",
                "approver_id": None,
                "opinion": None,
                "reason": None,
            }

            await start_approval_workflow(
                workflow_state
            )

        await session.commit()
        await session.refresh(approval)
        await session.refresh(suggestion)

    except Exception:
        await session.rollback()

        if (
            redis_session_created
            and approval.id is not None
        ):
            try:
                await delete_approval_session(
                    approval.id
                )
            except Exception:
                logger.exception(
                    "清理审批 Redis 会话失败：approval_id=%s",
                    approval.id,
                )

        raise

    return ApprovalDetail(
        approval=ApprovalRecordRead.model_validate(
            approval
        ),
        suggestion=(
            InterventionSuggestionRead.model_validate(
                suggestion
            )
        ),
    )


async def list_approvals(
    session: AsyncSession,
    current_user: User,
    status_filter: ApprovalStatus | None = None,
) -> list[ApprovalDetail]:
    """查询当前用户可访问的审批列表。

    Args:
        session: 数据库异步会话。
        current_user: 当前登录用户。
        status_filter: 可选的审批状态筛选条件。

    Returns:
        按提交时间倒序排列的审批及关联建议列表。
    """
    filters = []

    if status_filter is not None:
        filters.append(
            ApprovalRecord.status == status_filter
        )

    if current_user.role != "投放负责人":
        filters.append(
            Campaign.owner_id == current_user.id
        )

    rows = (
        await session.execute(
            select(
                ApprovalRecord,
                InterventionSuggestion,
            )
            .join(
                InterventionSuggestion,
                InterventionSuggestion.id
                == ApprovalRecord.suggestion_id,
            )
            .join(
                Campaign,
                Campaign.id
                == ApprovalRecord.campaign_id,
            )
            .where(*filters)
            .order_by(
                ApprovalRecord.submitted_at.desc(),
                ApprovalRecord.id.desc(),
            )
        )
    ).all()

    return [
        ApprovalDetail(
            approval=(
                ApprovalRecordRead.model_validate(
                    approval
                )
            ),
            suggestion=(
                InterventionSuggestionRead.model_validate(
                    suggestion
                )
            ),
        )
        for approval, suggestion in rows
    ]


async def get_approval_detail(
    session: AsyncSession,
    approval_id: int,
    current_user: User,
) -> ApprovalDetail | None:
    """查询当前用户可访问的审批详情。

    Args:
        session: 数据库异步会话。
        approval_id: 审批记录编号。
        current_user: 当前登录用户。

    Returns:
        审批记录及关联建议；记录不存在或无权访问时返回 None。
    """
    filters = [
        ApprovalRecord.id == approval_id,
    ]

    if current_user.role != "投放负责人":
        filters.append(
            Campaign.owner_id == current_user.id
        )

    row = (
        await session.execute(
            select(
                ApprovalRecord,
                InterventionSuggestion,
            )
            .join(
                InterventionSuggestion,
                InterventionSuggestion.id
                == ApprovalRecord.suggestion_id,
            )
            .join(
                Campaign,
                Campaign.id
                == ApprovalRecord.campaign_id,
            )
            .where(*filters)
        )
    ).first()

    if row is None:
        return None

    approval, suggestion = row

    return ApprovalDetail(
        approval=ApprovalRecordRead.model_validate(
            approval
        ),
        suggestion=(
            InterventionSuggestionRead.model_validate(
                suggestion
            )
        ),
    )


async def approve_approval(
    session: AsyncSession,
    approval_id: int,
    approver: User,
    opinion: str | None = None,
) -> ApprovalDetail | None:
    """通过一条等待人工处理的审批。

    Args:
        session: 数据库异步会话。
        approval_id: 待通过的审批记录编号。
        approver: 执行审批的投放负责人。
        opinion: 可选的审批意见。

    Returns:
        更新后的审批记录及关联建议；审批不存在时返回 None。

    Raises:
        ValueError: 审批已经被处理，不能重复审批。
        RuntimeError: 审批关联的干预建议不存在。
    """
    approval = await session.scalar(
        select(ApprovalRecord)
        .where(
            ApprovalRecord.id == approval_id
        )
        .with_for_update()
    )

    if approval is None:
        return None

    if approval.status != "待审批":
        raise ValueError(
            "当前审批状态不允许通过"
        )

    suggestion = await session.get(
        InterventionSuggestion,
        approval.suggestion_id,
    )

    if suggestion is None:
        raise RuntimeError(
            "审批关联的干预建议不存在"
        )

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    approval.status = "已通过"
    approval.approver_id = approver.id
    approval.approval_opinion = (
        opinion.strip()
        if opinion and opinion.strip()
        else None
    )
    approval.reject_reason = None
    approval.approved_at = now
    suggestion.status = "待执行"

    try:
        await session.commit()
        await session.refresh(approval)
        await session.refresh(suggestion)
    except Exception:
        await session.rollback()
        raise

    try:
        await resume_approval_workflow(
            campaign_id=approval.campaign_id,
            approval_id=approval.id,
            approved=True,
            approver_id=approver.id,
            opinion=approval.approval_opinion,
        )
    except Exception:
        logger.exception(
            "恢复审批工作流失败：approval_id=%s",
            approval.id,
        )

    try:
        await delete_approval_session(
            approval.id
        )
    except Exception:
        logger.exception(
            "删除审批 Redis 会话失败：approval_id=%s",
            approval.id,
        )

    return ApprovalDetail(
        approval=ApprovalRecordRead.model_validate(
            approval
        ),
        suggestion=(
            InterventionSuggestionRead.model_validate(
                suggestion
            )
        ),
    )


async def reject_approval(
    session: AsyncSession,
    approval_id: int,
    approver: User,
    reason: str,
) -> ApprovalDetail | None:
    """驳回一条等待人工处理的审批。

    Args:
        session: 数据库异步会话。
        approval_id: 待驳回的审批记录编号。
        approver: 执行审批的投放负责人。
        reason: 必填的驳回原因。

    Returns:
        更新后的审批记录及关联建议；审批不存在时返回 None。

    Raises:
        ValueError: 驳回原因为空或审批状态不允许驳回。
        RuntimeError: 审批关联的干预建议不存在。
    """
    reject_reason = reason.strip()

    if not reject_reason:
        raise ValueError("驳回原因不能为空")

    approval = await session.scalar(
        select(ApprovalRecord)
        .where(
            ApprovalRecord.id == approval_id
        )
        .with_for_update()
    )

    if approval is None:
        return None

    if approval.status != "待审批":
        raise ValueError(
            "当前审批状态不允许驳回"
        )

    suggestion = await session.get(
        InterventionSuggestion,
        approval.suggestion_id,
    )

    if suggestion is None:
        raise RuntimeError(
            "审批关联的干预建议不存在"
        )

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    approval.status = "已驳回"
    approval.approver_id = approver.id
    approval.approval_opinion = None
    approval.reject_reason = reject_reason
    approval.approved_at = now
    suggestion.status = "已驳回"

    try:
        await session.commit()
        await session.refresh(approval)
        await session.refresh(suggestion)
    except Exception:
        await session.rollback()
        raise

    try:
        await resume_approval_workflow(
            campaign_id=approval.campaign_id,
            approval_id=approval.id,
            approved=False,
            approver_id=approver.id,
            reason=approval.reject_reason,
        )
    except Exception:
        logger.exception(
            "恢复审批工作流失败：approval_id=%s",
            approval.id,
        )

    try:
        await delete_approval_session(
            approval.id
        )
    except Exception:
        logger.exception(
            "删除审批 Redis 会话失败：approval_id=%s",
            approval.id,
        )

    return ApprovalDetail(
        approval=ApprovalRecordRead.model_validate(
            approval
        ),
        suggestion=(
            InterventionSuggestionRead.model_validate(
                suggestion
            )
        ),
    )


async def expire_pending_approvals(
    session: AsyncSession,
    now: datetime | None = None,
) -> list[int]:
    """标记超过 72 小时仍未处理的审批。

    Args:
        session: 数据库异步会话。
        now: 可选的当前 UTC 时间，主要用于测试。

    Returns:
        本次被标记为已超时的审批记录编号列表。
    """
    current_time = now or datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    deadline = current_time - timedelta(hours=72)

    approvals = list(
        (
            await session.scalars(
                select(ApprovalRecord)
                .where(
                    ApprovalRecord.status == "待审批",
                    ApprovalRecord.submitted_at
                    <= deadline,
                )
                .with_for_update(
                    skip_locked=True
                )
            )
        ).all()
    )

    if not approvals:
        return []

    for approval in approvals:
        approval.status = "已超时"
        approval.approval_opinion = (
            "审批超过72小时，已标记超时"
        )
        approval.approved_at = current_time

        suggestion = await session.get(
            InterventionSuggestion,
            approval.suggestion_id,
        )

        if (
            suggestion is not None
            and suggestion.status == "审批中"
        ):
            suggestion.status = "审批超时"

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    for approval in approvals:
        try:
            await delete_approval_session(
                approval.id
            )
        except Exception:
            logger.exception(
                "清理超时审批会话失败：approval_id=%s",
                approval.id,
            )

        logger.warning(
            "审批已超时，请投放负责人处理："
            "approval_id=%s, suggestion_id=%s, "
            "campaign_id=%s",
            approval.id,
            approval.suggestion_id,
            approval.campaign_id,
        )

    return [
        approval.id
        for approval in approvals
    ]
