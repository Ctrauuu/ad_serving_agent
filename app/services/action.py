import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ad_platform import call_ad_platform_tool
from app.infrastructure.redis import redis_client
from app.models import (
    ActionExecution,
    AdGroup,
    ApprovalRecord,
    InterventionSuggestion,
    User,
)


logger = logging.getLogger(__name__)

_ACTION_LOCK_TTL_SECONDS = 60

_RELEASE_ACTION_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


def build_action_lock_key(
    target_type: str,
    target_id: int,
) -> str:
    """生成目标对象的动作锁 Key。

    Args:
        target_type: 动作目标类型，例如 ad_group。
        target_id: 本地目标对象编号。

    Returns:
        带动作执行命名空间的 Redis Key。
    """
    return (
        f"lock:action:{target_type}:"
        f"{target_id}"
    )


async def acquire_action_lock(
    target_type: str,
    target_id: int,
) -> str | None:
    """尝试获取目标对象的分布式动作锁。

    Args:
        target_type: 动作目标类型。
        target_id: 本地目标对象编号。

    Returns:
        获取成功时返回随机锁令牌；对象已被锁定时返回 None。
    """
    token = uuid4().hex

    acquired = await redis_client.set(
        build_action_lock_key(
            target_type,
            target_id,
        ),
        token,
        ex=_ACTION_LOCK_TTL_SECONDS,
        nx=True,
    )

    return token if acquired else None


async def release_action_lock(
    target_type: str,
    target_id: int,
    token: str,
) -> bool:
    """仅在令牌匹配时原子释放动作锁。

    Args:
        target_type: 动作目标类型。
        target_id: 本地目标对象编号。
        token: 获取锁时返回的随机令牌。

    Returns:
        当前调用实际删除锁时返回 True，否则返回 False。
    """
    deleted = cast(
        int,
        await redis_client.eval(
            _RELEASE_ACTION_LOCK_SCRIPT,
            1,
            build_action_lock_key(
                target_type,
                target_id,
            ),
            token,
        ),
    )

    return bool(deleted)


def _read_positive_decimal(
    values: dict[str, Any],
    keys: tuple[str, ...],
    field_name: str,
) -> Decimal:
    """读取并校验一个正数动作参数。

    Args:
        values: 动作参数或平台状态。
        keys: 按优先级尝试读取的字段名。
        field_name: 错误信息中使用的业务字段名。

    Returns:
        校验通过的 Decimal 数值。

    Raises:
        ValueError: 参数缺失、格式错误、非有限数或不大于零。
    """
    value = next(
        (
            values[key]
            for key in keys
            if values.get(key) is not None
        ),
        None,
    )

    if value is None:
        raise ValueError(
            f"缺少动作参数：{field_name}"
        )

    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(
            f"动作参数格式错误：{field_name}"
        ) from exc

    if (
        not number.is_finite()
        or number <= 0
    ):
        raise ValueError(
            f"动作参数必须大于 0：{field_name}"
        )

    return number


def build_action_tool_call(
    suggestion: InterventionSuggestion,
    platform_id: str,
    before_state: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """把已审批建议转换为固定 MCP 工具调用。

    Args:
        suggestion: 已通过审批的干预建议。
        platform_id: 本地目标对应的平台广告组 ID。
        before_state: MCP 返回的动作前完整状态。

    Returns:
        MCP 工具名称和经过校验的调用参数。

    Raises:
        ValueError: 动作不受支持或动作参数不完整。
    """
    action_type = suggestion.action_type
    params = suggestion.action_params or {}

    if action_type == "pause":
        return (
            "pause_ad_group",
            {
                "ad_platform_group_id": (
                    platform_id
                )
            },
        )

    if action_type in {
        "adjust_budget",
        "increase_budget",
    }:
        if (
            action_type == "increase_budget"
            and params.get("add_budget") is not None
        ):
            current_budget = (
                _read_positive_decimal(
                    before_state,
                    ("budget_daily",),
                    "当前日预算",
                )
            )
            added_budget = (
                _read_positive_decimal(
                    params,
                    ("add_budget",),
                    "增加预算",
                )
            )
            budget_daily = (
                current_budget + added_budget
            )
        else:
            budget_daily = (
                _read_positive_decimal(
                    params,
                    (
                        "budget_daily",
                        "new_budget_daily",
                    ),
                    "调整后日预算",
                )
            )

        return (
            "adjust_budget",
            {
                "platform_id": platform_id,
                "budget_daily": float(
                    budget_daily
                ),
            },
        )

    if action_type == "adjust_bid":
        bid = _read_positive_decimal(
            params,
            ("bid", "new_bid"),
            "调整后出价",
        )

        return (
            "adjust_bid",
            {
                "ad_platform_group_id": (
                    platform_id
                ),
                "bid": float(bid),
            },
        )

    if action_type == "replace_creative":
        value = params.get(
            "new_creative_id",
            params.get("creative_id"),
        )

        try:
            creative_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "缺少或无法识别新素材编号"
            ) from exc

        if (
            isinstance(value, bool)
            or creative_id <= 0
        ):
            raise ValueError(
                "新素材编号必须大于 0"
            )

        return (
            "replace_creative",
            {
                "ad_platform_group_id": (
                    platform_id
                ),
                "creative_id": creative_id,
            },
        )

    raise ValueError(
        f"不支持执行的动作类型：{action_type}"
    )


def build_rollback_tool_call(
    execution: ActionExecution,
    platform_id: str,
) -> tuple[str, dict[str, Any]]:
    """根据执行前快照生成对应的反向 MCP 动作。

    Args:
        execution: 已成功且可回滚的动作执行记录。
        platform_id: 目标广告组的平台编号。

    Returns:
        反向 MCP 工具名称和调用参数。

    Raises:
        ValueError: 缺少回滚快照、动作类型不支持，
            或快照不满足安全回滚条件。
    """
    before_state = execution.before_state
    after_state = execution.after_state

    if before_state is None or after_state is None:
        raise ValueError("缺少动作快照，无法回滚")

    if execution.action_type == "pause":
        if (
            before_state.get("status") != "已上线"
            or after_state.get("status") != "已暂停"
        ):
            raise ValueError("暂停动作快照不满足回滚条件")

        return (
            "resume_ad_group",
            {
                "ad_platform_group_id": platform_id,
            },
        )

    if execution.action_type in {
        "adjust_budget",
        "increase_budget",
    }:
        budget_daily = _read_positive_decimal(
            before_state,
            ("budget_daily",),
            "回滚日预算",
        )

        return (
            "adjust_budget",
            {
                "platform_id": platform_id,
                "budget_daily": float(budget_daily),
            },
        )

    if execution.action_type == "adjust_bid":
        bid = _read_positive_decimal(
            before_state,
            ("bid",),
            "回滚出价",
        )

        return (
            "adjust_bid",
            {
                "ad_platform_group_id": platform_id,
                "bid": float(bid),
            },
        )

    if execution.action_type == "replace_creative":
        creative_id = before_state.get("creative_id")

        if (
            isinstance(creative_id, bool)
            or not isinstance(creative_id, int)
            or creative_id <= 0
        ):
            raise ValueError("回滚素材编号无效")

        return (
            "replace_creative",
            {
                "ad_platform_group_id": platform_id,
                "creative_id": creative_id,
            },
        )

    raise ValueError(
        f"不支持回滚的动作类型：{execution.action_type}"
    )


def is_platform_state_unchanged(
    expected_after_state: dict[str, Any],
    current_state: dict[str, Any],
) -> bool:
    """判断平台当前状态是否仍与动作后的快照一致。

    Args:
        expected_after_state: 原动作成功后保存的平台状态快照。
        current_state: 回滚前刚从 MCP 获取的平台当前状态。

    Returns:
        当前状态包含全部快照字段且字段值一致时返回 True；
        快照为空、字段缺失或任一值变化时返回 False。
    """
    return bool(expected_after_state) and all(
        current_state.get(key) == value
        for key, value in expected_after_state.items()
    )


async def _get_action_execution_context(
    session: AsyncSession,
    approval_id: int,
) -> tuple[
    ApprovalRecord,
    InterventionSuggestion,
    AdGroup,
] | None:
    """读取并校验一个可执行的审批上下文。

    Args:
        session: 数据库异步会话。
        approval_id: 已通过的审批记录编号。

    Returns:
        审批、建议和目标广告组；审批不存在时返回 None。

    Raises:
        ValueError: 审批未通过、建议状态不允许执行，
            或目标对象信息不完整。
        RuntimeError: 审批关联数据不存在或关系不一致。
    """
    approval = await session.get(
        ApprovalRecord,
        approval_id,
    )

    if approval is None:
        return None

    if approval.status != "已通过":
        raise ValueError(
            "审批尚未通过，不能执行动作"
        )

    suggestion = await session.get(
        InterventionSuggestion,
        approval.suggestion_id,
    )

    if suggestion is None:
        raise RuntimeError(
            "审批关联的干预建议不存在"
        )

    if suggestion.status not in {
        "待执行",
        "执行失败",
    }:
        raise ValueError(
            "当前建议状态不允许执行"
        )

    if (
        suggestion.campaign_id
        != approval.campaign_id
    ):
        raise RuntimeError(
            "审批与建议所属活动不一致"
        )

    if suggestion.target_type != "ad_group":
        raise ValueError(
            "当前仅支持广告组动作执行"
        )

    ad_group = await session.get(
        AdGroup,
        suggestion.target_id,
    )

    if ad_group is None:
        raise RuntimeError(
            "建议关联的广告组不存在"
        )

    if (
        ad_group.campaign_id
        != suggestion.campaign_id
    ):
        raise RuntimeError(
            "广告组与建议所属活动不一致"
        )

    if not ad_group.ad_platform_group_id:
        raise ValueError(
            "广告组尚未创建平台任务"
        )

    return approval, suggestion, ad_group


def _sync_ad_group_from_state(
    ad_group: AdGroup,
    state: dict[str, Any],
) -> None:
    """把平台最新状态同步到本地广告组。

    Args:
        ad_group: 本地广告组记录。
        state: MCP 返回的平台完整状态。

    Returns:
        无返回值。
    """
    if state.get("status") is not None:
        ad_group.status = str(state["status"])

    if state.get("budget_daily") is not None:
        ad_group.budget_daily = Decimal(
            str(state["budget_daily"])
        )

    if state.get("bid") is not None:
        ad_group.bid = Decimal(
            str(state["bid"])
        )

    if state.get("creative_id") is not None:
        ad_group.creative_id = int(
            state["creative_id"]
        )


async def execute_approved_action(
    session: AsyncSession,
    approval_id: int,
    executor: User,
) -> ActionExecution | None:
    """执行一条已经通过审批的广告平台动作。

    Args:
        session: 数据库异步会话。
        approval_id: 已通过的审批记录编号。
        executor: 触发本次执行的用户。

    Returns:
        成功或失败的动作执行记录；审批不存在时返回 None。

    Raises:
        ValueError: 审批、建议或目标状态不允许执行，
            或目标对象正在执行其他动作。
        RuntimeError: 审批关联数据不完整。
    """
    context = await _get_action_execution_context(
        session,
        approval_id,
    )

    if context is None:
        return None

    approval, suggestion, ad_group = context

    lock_token = await acquire_action_lock(
        suggestion.target_type,
        suggestion.target_id,
    )

    if lock_token is None:
        raise ValueError(
            "该对象有动作正在执行，请稍后重试"
        )

    platform_id = (
        ad_group.ad_platform_group_id
    )

    execution = ActionExecution(
        approval_id=approval.id,
        suggestion_id=suggestion.id,
        campaign_id=suggestion.campaign_id,
        target_type=suggestion.target_type,
        target_id=suggestion.target_id,
        action_type=suggestion.action_type,
        action_params=dict(
            suggestion.action_params or {}
        ),
        executor_id=executor.id,
        status="待执行",
        rollback_status="不适用",
    )
    session.add(execution)

    try:
        try:
            before_state = (
                await call_ad_platform_tool(
                    "get_ad_status",
                    {
                        "platform_id": platform_id
                    },
                )
            )
            execution.before_state = before_state

            tool_name, tool_arguments = (
                build_action_tool_call(
                    suggestion,
                    platform_id,
                    before_state,
                )
            )
            execution.tool_name = tool_name
            execution.status = "执行中"

        except Exception as exc:
            execution.status = "失败"
            execution.error_message = str(exc)[:512]
            execution.executed_at = datetime.now(
                timezone.utc
            ).replace(tzinfo=None)
            suggestion.status = "执行失败"

            await session.commit()
            await session.refresh(execution)
            return execution

        # 先把动作前快照写入数据库，
        # 再真正修改广告平台状态。
        await session.commit()
        await session.refresh(execution)

        try:
            tool_result = (
                await call_ad_platform_tool(
                    tool_name,
                    tool_arguments,
                )
            )
            execution.tool_result = tool_result

            after_state = (
                await call_ad_platform_tool(
                    "get_ad_status",
                    {
                        "platform_id": platform_id
                    },
                )
            )
            execution.after_state = after_state

        except Exception as exc:
            execution.status = "失败"
            execution.error_message = str(exc)[:512]
            execution.rollback_status = (
                "需人工处理"
                if execution.tool_result
                else "不适用"
            )
            suggestion.status = "执行失败"

        else:
            execution.status = "成功"
            execution.error_message = None
            execution.rollback_status = "可回滚"
            suggestion.status = "已执行"

            _sync_ad_group_from_state(
                ad_group,
                after_state,
            )

        execution.executed_at = datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

        await session.commit()
        await session.refresh(execution)

        return execution

    finally:
        try:
            released = await release_action_lock(
                suggestion.target_type,
                suggestion.target_id,
                lock_token,
            )

            if not released:
                logger.warning(
                    "动作锁已过期或被替换："
                    "target_type=%s, target_id=%s",
                    suggestion.target_type,
                    suggestion.target_id,
                )

        except Exception:
            logger.exception(
                "释放动作锁失败："
                "target_type=%s, target_id=%s",
                suggestion.target_type,
                suggestion.target_id,
            )


async def list_action_executions(
    session: AsyncSession,
    campaign_id: int,
) -> list[ActionExecution]:
    """查询指定活动的动作执行记录。

    Args:
        session: 数据库异步会话。
        campaign_id: 活动编号。

    Returns:
        按创建时间和编号倒序排列的动作执行记录。
    """
    result = await session.scalars(
        select(ActionExecution)
        .where(
            ActionExecution.campaign_id
            == campaign_id
        )
        .order_by(
            ActionExecution.created_at.desc(),
            ActionExecution.id.desc(),
        )
    )

    return list(result)


async def rollback_action(
    session: AsyncSession,
    action_id: int,
    executor: User,
) -> ActionExecution | None:
    """回滚一条成功且可回滚的广告平台动作。

    Args:
        session: 数据库异步会话。
        action_id: 要回滚的动作执行记录编号。
        executor: 发起回滚的投放负责人。

    Returns:
        更新后的动作执行记录；记录不存在时返回 None。

    Raises:
        ValueError: 动作状态不允许回滚、目标数据不完整、
            存在并发动作，或平台状态已被其他操作改动。
        RuntimeError: 目标广告组与执行记录所属活动不一致。
    """
    execution = await session.get(
        ActionExecution,
        action_id,
    )

    if execution is None:
        return None

    if execution.status != "成功":
        raise ValueError("只有成功动作可以回滚")

    if execution.rollback_status != "可回滚":
        raise ValueError("当前动作状态不允许回滚")

    if execution.target_type != "ad_group":
        raise ValueError("当前仅支持广告组动作回滚")

    if (
        execution.before_state is None
        or execution.after_state is None
    ):
        raise ValueError("缺少动作快照，无法回滚")

    ad_group = await session.get(
        AdGroup,
        execution.target_id,
    )

    if ad_group is None:
        raise RuntimeError("动作关联的广告组不存在")

    if ad_group.campaign_id != execution.campaign_id:
        raise RuntimeError(
            "广告组与动作记录所属活动不一致"
        )

    if not ad_group.ad_platform_group_id:
        raise ValueError("广告组尚未创建平台任务")

    lock_token = await acquire_action_lock(
        execution.target_type,
        execution.target_id,
    )

    if lock_token is None:
        raise ValueError(
            "该对象有动作正在执行，请稍后重试"
        )

    platform_id = ad_group.ad_platform_group_id

    try:
        try:
            current_state = await call_ad_platform_tool(
                "get_ad_status",
                {"platform_id": platform_id},
            )
        except Exception as exc:
            execution.rollback_status = "回滚失败"
            execution.error_message = (
                f"回滚前查询平台状态失败：{exc}"
            )[:512]
            await session.commit()
            await session.refresh(execution)
            return execution

        if not is_platform_state_unchanged(
            execution.after_state,
            current_state,
        ):
            execution.rollback_status = "需人工处理"
            execution.error_message = (
                "平台状态已被改动，无法安全回滚"
            )
            await session.commit()
            await session.refresh(execution)
            raise ValueError(
                "平台状态已被改动，需人工处理"
            )

        try:
            tool_name, tool_arguments = (
                build_rollback_tool_call(
                    execution,
                    platform_id,
                )
            )
        except ValueError as exc:
            execution.rollback_status = "需人工处理"
            execution.error_message = str(exc)[:512]
            await session.commit()
            await session.refresh(execution)
            raise

        execution.rollback_status = "回滚中"
        await session.commit()
        await session.refresh(execution)

        rollback_result: dict[str, Any] | None = None
        rollback_after_state: dict[str, Any] | None = None

        try:
            rollback_result = await call_ad_platform_tool(
                tool_name,
                tool_arguments,
            )
            rollback_after_state = (
                await call_ad_platform_tool(
                    "get_ad_status",
                    {"platform_id": platform_id},
                )
            )
        except Exception as exc:
            execution.rollback_status = (
                "需人工处理"
                if rollback_result is not None
                else "回滚失败"
            )
            execution.error_message = (
                f"回滚执行失败：{exc}"
            )[:512]
        else:
            execution.rollback_status = "已回滚"
            execution.error_message = None

            _sync_ad_group_from_state(
                ad_group,
                rollback_after_state,
            )

        tool_result = dict(execution.tool_result or {})
        tool_result["rollback"] = {
            "tool_name": tool_name,
            "result": rollback_result,
            "after_state": rollback_after_state,
            "executor_id": executor.id,
            "executed_at": datetime.now(
                timezone.utc
            ).replace(tzinfo=None).isoformat(),
        }
        execution.tool_result = tool_result

        await session.commit()
        await session.refresh(execution)

        return execution

    finally:
        try:
            released = await release_action_lock(
                execution.target_type,
                execution.target_id,
                lock_token,
            )

            if not released:
                logger.warning(
                    "回滚动作锁已过期或被替换："
                    "target_type=%s, target_id=%s",
                    execution.target_type,
                    execution.target_id,
                )
        except Exception:
            logger.exception(
                "释放回滚动作锁失败："
                "target_type=%s, target_id=%s",
                execution.target_type,
                execution.target_id,
            )
