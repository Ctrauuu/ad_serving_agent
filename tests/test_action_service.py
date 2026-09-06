from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.redis import redis_client
from app.models import (
    ActionExecution,
    AdGroup,
    ApprovalRecord,
    InterventionSuggestion,
    User,
)
from app.services.action import (
    _get_action_execution_context,
    acquire_action_lock,
    build_action_tool_call,
    build_action_lock_key,
    build_rollback_tool_call,
    execute_approved_action,
    is_platform_state_unchanged,
    list_action_executions,
    release_action_lock,
    rollback_action,
)


def make_action_suggestion(
    action_type: str,
    action_params: dict[str, object],
) -> InterventionSuggestion:
    """构造 MCP 动作映射测试使用的建议。

    Args:
        action_type: 建议动作类型。
        action_params: 建议动作参数。

    Returns:
        可供动作映射函数读取的建议对象。
    """
    return InterventionSuggestion(
        action_type=action_type,
        action_params=action_params,
    )


def make_execution_context() -> tuple[
    ApprovalRecord,
    InterventionSuggestion,
    AdGroup,
]:
    """构造动作执行上下文测试数据。

    Returns:
        已通过审批、待执行建议和对应平台广告组。
    """
    approval = ApprovalRecord(
        id=10,
        suggestion_id=4,
        campaign_id=8,
        status="已通过",
    )
    suggestion = InterventionSuggestion(
        id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        action_type="pause",
        action_params={"ad_group_id": 32},
        status="待执行",
    )
    ad_group = AdGroup(
        id=32,
        campaign_id=8,
        ad_platform_group_id="mock-group",
    )
    return approval, suggestion, ad_group


def make_rollback_context() -> tuple[
    ActionExecution,
    AdGroup,
]:
    """构造可安全回滚的暂停动作和对应广告组。

    Returns:
        成功且可回滚的执行记录，以及其平台广告组。
    """
    execution = ActionExecution(
        id=6,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        action_type="pause",
        action_params={"ad_group_id": 32},
        before_state={
            "status": "已上线",
            "budget_daily": 100,
            "bid": 5,
            "creative_id": 1,
        },
        after_state={
            "status": "已暂停",
            "budget_daily": 100,
            "bid": 5,
            "creative_id": 1,
        },
        tool_result={"status": "已暂停"},
        status="成功",
        rollback_status="可回滚",
    )
    ad_group = AdGroup(
        id=32,
        campaign_id=8,
        ad_platform_group_id="mock-group",
    )
    return execution, ad_group


@pytest.mark.asyncio
async def test_action_lock_uses_token_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证动作锁使用 NX、过期时间和随机令牌。"""
    set_value = AsyncMock(return_value=True)
    monkeypatch.setattr(redis_client, "set", set_value)

    token = await acquire_action_lock(
        "ad_group",
        32,
    )

    assert token is not None
    set_value.assert_awaited_once_with(
        "lock:action:ad_group:32",
        token,
        ex=60,
        nx=True,
    )


@pytest.mark.asyncio
async def test_action_lock_reports_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证目标已有动作锁时返回获取失败。"""
    monkeypatch.setattr(
        redis_client,
        "set",
        AsyncMock(return_value=None),
    )

    token = await acquire_action_lock(
        "ad_group",
        32,
    )

    assert token is None


@pytest.mark.asyncio
async def test_action_lock_release_is_token_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证释放动作锁时通过 Lua 原子校验令牌。"""
    evaluate = AsyncMock(return_value=1)
    monkeypatch.setattr(
        redis_client,
        "eval",
        evaluate,
    )

    released = await release_action_lock(
        "ad_group",
        32,
        "lock-token",
    )

    assert released is True
    args = evaluate.await_args.args
    assert "redis.call" in args[0]
    assert args[1:] == (
        1,
        build_action_lock_key("ad_group", 32),
        "lock-token",
    )


@pytest.mark.parametrize(
    ("action_type", "params", "tool_name", "arguments"),
    [
        (
            "pause",
            {"ad_group_id": 32},
            "pause_ad_group",
            {"ad_platform_group_id": "mock-group"},
        ),
        (
            "adjust_budget",
            {"new_budget_daily": "120.50"},
            "adjust_budget",
            {
                "platform_id": "mock-group",
                "budget_daily": 120.5,
            },
        ),
        (
            "adjust_bid",
            {"new_bid": "6.25"},
            "adjust_bid",
            {
                "ad_platform_group_id": "mock-group",
                "bid": 6.25,
            },
        ),
        (
            "replace_creative",
            {"new_creative_id": "2"},
            "replace_creative",
            {
                "ad_platform_group_id": "mock-group",
                "creative_id": 2,
            },
        ),
    ],
)
def test_build_action_tool_call_uses_whitelist(
    action_type: str,
    params: dict[str, object],
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    """验证支持动作只能映射到固定 MCP 工具和参数。"""
    suggestion = make_action_suggestion(
        action_type,
        params,
    )

    result = build_action_tool_call(
        suggestion,
        "mock-group",
        {"budget_daily": 100},
    )

    assert result == (tool_name, arguments)


def test_build_action_tool_call_supports_legacy_budget() -> None:
    """验证已有增量预算记录可转换为绝对日预算。"""
    suggestion = make_action_suggestion(
        "increase_budget",
        {"add_budget": 50},
    )

    tool_name, arguments = build_action_tool_call(
        suggestion,
        "mock-group",
        {"budget_daily": 100},
    )

    assert tool_name == "adjust_budget"
    assert arguments["budget_daily"] == 150


def test_build_action_tool_call_rejects_non_platform_action() -> None:
    """验证观察类建议不能被当作平台动作执行。"""
    suggestion = make_action_suggestion(
        "extend_observation",
        {},
    )

    with pytest.raises(ValueError, match="不支持执行"):
        build_action_tool_call(
            suggestion,
            "mock-group",
            {"status": "已上线"},
        )


@pytest.mark.parametrize(
    (
        "action_type",
        "before_state",
        "after_state",
        "tool_name",
        "arguments",
    ),
    [
        (
            "pause",
            {"status": "已上线"},
            {"status": "已暂停"},
            "resume_ad_group",
            {"ad_platform_group_id": "mock-group"},
        ),
        (
            "adjust_budget",
            {"budget_daily": 100},
            {"budget_daily": 120},
            "adjust_budget",
            {"platform_id": "mock-group", "budget_daily": 100.0},
        ),
        (
            "adjust_bid",
            {"bid": 5},
            {"bid": 6},
            "adjust_bid",
            {"ad_platform_group_id": "mock-group", "bid": 5.0},
        ),
        (
            "replace_creative",
            {"creative_id": 1},
            {"creative_id": 2},
            "replace_creative",
            {"ad_platform_group_id": "mock-group", "creative_id": 1},
        ),
    ],
)
def test_build_rollback_tool_call_restores_before_state(
    action_type: str,
    before_state: dict[str, object],
    after_state: dict[str, object],
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    """验证各类成功动作均恢复动作前的目标字段。"""
    execution = ActionExecution(
        action_type=action_type,
        before_state=before_state,
        after_state=after_state,
    )

    result = build_rollback_tool_call(
        execution,
        "mock-group",
    )

    assert result == (tool_name, arguments)


def test_build_rollback_tool_call_requires_snapshots() -> None:
    """验证缺少前后快照时拒绝回滚。"""
    execution = ActionExecution(
        action_type="pause",
        before_state=None,
        after_state=None,
    )

    with pytest.raises(ValueError, match="缺少动作快照"):
        build_rollback_tool_call(
            execution,
            "mock-group",
        )


def test_platform_state_comparison_requires_unchanged_snapshot() -> None:
    """验证回滚只接受与动作后快照一致的平台状态。"""
    expected = {
        "status": "已暂停",
        "budget_daily": 120,
    }

    assert is_platform_state_unchanged(
        expected,
        {**expected, "creative_id": 2},
    )
    assert not is_platform_state_unchanged(
        expected,
        {"status": "已暂停", "budget_daily": 150},
    )
    assert not is_platform_state_unchanged({}, expected)


@pytest.mark.asyncio
async def test_get_action_execution_context_validates_relations() -> None:
    """验证已通过审批可加载同活动的平台广告组。"""
    approval, suggestion, ad_group = make_execution_context()
    session = AsyncMock()
    session.get.side_effect = [
        approval,
        suggestion,
        ad_group,
    ]

    context = await _get_action_execution_context(
        session,
        approval.id,
    )

    assert context == (
        approval,
        suggestion,
        ad_group,
    )


@pytest.mark.asyncio
async def test_get_action_execution_context_requires_approval() -> None:
    """验证未通过审批不能进入动作执行流程。"""
    approval, _, _ = make_execution_context()
    approval.status = "待审批"
    session = AsyncMock()
    session.get.return_value = approval

    with pytest.raises(ValueError, match="审批尚未通过"):
        await _get_action_execution_context(
            session,
            approval.id,
        )

    assert session.get.await_count == 1


@pytest.mark.asyncio
async def test_get_action_execution_context_blocks_cross_campaign() -> None:
    """验证广告组与建议跨活动关联时拒绝执行。"""
    approval, suggestion, ad_group = make_execution_context()
    ad_group.campaign_id = 9
    session = AsyncMock()
    session.get.side_effect = [
        approval,
        suggestion,
        ad_group,
    ]

    with pytest.raises(RuntimeError, match="广告组与建议"):
        await _get_action_execution_context(
            session,
            approval.id,
        )


def make_executor() -> User:
    """构造动作执行测试使用的登录用户。

    Returns:
        带固定编号的投放用户。
    """
    return User(
        id=7,
        username="operator",
        password_hash="hash",
        display_name="投放人员",
        role="投放人员",
    )


@pytest.mark.asyncio
async def test_execute_approved_action_saves_snapshots_and_syncs_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证成功执行会保存前后快照并同步本地广告组。"""
    approval, suggestion, ad_group = make_execution_context()
    session = AsyncMock(spec=AsyncSession)
    before_state = {
        "status": "已上线",
        "budget_daily": 100,
        "bid": 5,
        "creative_id": 1,
    }
    after_state = {
        **before_state,
        "status": "已暂停",
    }
    events: list[str] = []

    async def call_tool(
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        """按调用顺序返回模拟平台状态和执行结果。"""
        events.append(tool_name)
        if tool_name == "pause_ad_group":
            return {"status": "已暂停"}
        return (
            before_state
            if events.count("get_ad_status") == 1
            else after_state
        )

    async def commit() -> None:
        """记录数据库提交发生的顺序。"""
        events.append("commit")

    monkeypatch.setattr(
        "app.services.action._get_action_execution_context",
        AsyncMock(
            return_value=(approval, suggestion, ad_group)
        ),
    )
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value="lock-token"),
    )
    release = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.action.release_action_lock",
        release,
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )
    session.commit.side_effect = commit

    result = await execute_approved_action(
        session,
        approval.id,
        make_executor(),
    )

    assert result is not None
    assert result.status == "成功"
    assert result.before_state == before_state
    assert result.after_state == after_state
    assert result.rollback_status == "可回滚"
    assert suggestion.status == "已执行"
    assert ad_group.status == "已暂停"
    assert ad_group.budget_daily == Decimal("100")
    assert ad_group.bid == Decimal("5")
    assert ad_group.creative_id == 1
    assert events == [
        "get_ad_status",
        "commit",
        "pause_ad_group",
        "get_ad_status",
        "commit",
    ]
    release.assert_awaited_once_with(
        "ad_group",
        32,
        "lock-token",
    )


@pytest.mark.asyncio
async def test_execute_approved_action_records_snapshot_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证动作前快照失败仍会保存失败记录。"""
    approval, suggestion, ad_group = make_execution_context()
    session = AsyncMock(spec=AsyncSession)
    call_tool = AsyncMock(
        side_effect=RuntimeError("平台不可用")
    )
    monkeypatch.setattr(
        "app.services.action._get_action_execution_context",
        AsyncMock(
            return_value=(approval, suggestion, ad_group)
        ),
    )
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value="lock-token"),
    )
    monkeypatch.setattr(
        "app.services.action.release_action_lock",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    result = await execute_approved_action(
        session,
        approval.id,
        make_executor(),
    )

    assert result is not None
    assert result.status == "失败"
    assert result.before_state is None
    assert result.error_message == "平台不可用"
    assert result.rollback_status == "不适用"
    assert suggestion.status == "执行失败"
    session.commit.assert_awaited_once()
    call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_approved_action_marks_uncertain_platform_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证平台已修改但后快照失败时标记人工处理。"""
    approval, suggestion, ad_group = make_execution_context()
    session = AsyncMock(spec=AsyncSession)
    before_state = {
        "status": "已上线",
        "budget_daily": 100,
    }
    call_tool = AsyncMock(
        side_effect=[
            before_state,
            {"status": "已暂停"},
            RuntimeError("查询后状态失败"),
        ]
    )
    monkeypatch.setattr(
        "app.services.action._get_action_execution_context",
        AsyncMock(
            return_value=(approval, suggestion, ad_group)
        ),
    )
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value="lock-token"),
    )
    monkeypatch.setattr(
        "app.services.action.release_action_lock",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    result = await execute_approved_action(
        session,
        approval.id,
        make_executor(),
    )

    assert result is not None
    assert result.status == "失败"
    assert result.before_state == before_state
    assert result.after_state is None
    assert result.tool_result == {"status": "已暂停"}
    assert result.rollback_status == "需人工处理"
    assert suggestion.status == "执行失败"
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_execute_approved_action_stops_on_lock_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证同一对象已有动作执行时不会调用广告平台。"""
    approval, suggestion, ad_group = make_execution_context()
    session = AsyncMock(spec=AsyncSession)
    call_tool = AsyncMock()
    monkeypatch.setattr(
        "app.services.action._get_action_execution_context",
        AsyncMock(
            return_value=(approval, suggestion, ad_group)
        ),
    )
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    with pytest.raises(ValueError, match="动作正在执行"):
        await execute_approved_action(
            session,
            approval.id,
            make_executor(),
        )

    call_tool.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_list_action_executions_filters_and_orders() -> None:
    """验证执行记录按活动筛选并按最新记录倒序返回。"""
    records = [
        object(),
        object(),
    ]
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = iter(records)

    result = await list_action_executions(
        session,
        campaign_id=8,
    )

    assert result == records
    statement = session.scalars.await_args.args[0]
    sql = str(statement)
    assert "action_execution.campaign_id" in sql
    assert "ORDER BY action_execution.created_at DESC" in sql
    assert statement.compile().params == {
        "campaign_id_1": 8
    }


@pytest.mark.asyncio
async def test_rollback_action_restores_before_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证回滚成功后恢复平台与本地广告组的动作前状态。"""
    execution, ad_group = make_rollback_context()
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = [execution, ad_group]
    calls: list[str] = []

    async def call_tool(
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        """按回滚顺序返回平台状态和恢复结果。"""
        calls.append(tool_name)
        if tool_name == "resume_ad_group":
            return {"status": "已上线"}
        return (
            execution.after_state
            if calls.count("get_ad_status") == 1
            else execution.before_state
        )

    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value="lock-token"),
    )
    release = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.action.release_action_lock",
        release,
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    result = await rollback_action(
        session,
        execution.id,
        make_executor(),
    )

    assert result is execution
    assert execution.rollback_status == "已回滚"
    assert execution.error_message is None
    assert ad_group.status == "已上线"
    assert ad_group.budget_daily == Decimal("100")
    assert ad_group.bid == Decimal("5")
    assert execution.tool_result["rollback"]["tool_name"] == (
        "resume_ad_group"
    )
    assert execution.tool_result["rollback"]["after_state"] == (
        execution.before_state
    )
    assert calls == [
        "get_ad_status",
        "resume_ad_group",
        "get_ad_status",
    ]
    assert session.commit.await_count == 2
    release.assert_awaited_once_with(
        "ad_group",
        32,
        "lock-token",
    )


@pytest.mark.asyncio
async def test_rollback_action_requires_manual_handling_when_state_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证平台状态偏离动作后快照时不执行反向 MCP 工具。"""
    execution, ad_group = make_rollback_context()
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = [execution, ad_group]
    call_tool = AsyncMock(
        return_value={
            **execution.after_state,
            "budget_daily": 150,
        }
    )
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value="lock-token"),
    )
    monkeypatch.setattr(
        "app.services.action.release_action_lock",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    with pytest.raises(ValueError, match="需人工处理"):
        await rollback_action(
            session,
            execution.id,
            make_executor(),
        )

    assert execution.rollback_status == "需人工处理"
    assert execution.error_message == "平台状态已被改动，无法安全回滚"
    assert session.commit.await_count == 1
    call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_rollback_action_records_platform_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证反向 MCP 工具失败时保留失败状态和审计信息。"""
    execution, ad_group = make_rollback_context()
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = [execution, ad_group]
    call_tool = AsyncMock(
        side_effect=[
            execution.after_state,
            RuntimeError("平台调用超时"),
        ]
    )
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value="lock-token"),
    )
    monkeypatch.setattr(
        "app.services.action.release_action_lock",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    result = await rollback_action(
        session,
        execution.id,
        make_executor(),
    )

    assert result is execution
    assert execution.rollback_status == "回滚失败"
    assert execution.error_message == "回滚执行失败：平台调用超时"
    assert execution.tool_result["rollback"]["result"] is None
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_rollback_action_stops_on_lock_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证同一广告组已有动作执行时拒绝并发回滚。"""
    execution, ad_group = make_rollback_context()
    session = AsyncMock(spec=AsyncSession)
    session.get.side_effect = [execution, ad_group]
    call_tool = AsyncMock()
    monkeypatch.setattr(
        "app.services.action.acquire_action_lock",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.action.call_ad_platform_tool",
        call_tool,
    )

    with pytest.raises(ValueError, match="动作正在执行"):
        await rollback_action(
            session,
            execution.id,
            make_executor(),
        )

    call_tool.assert_not_awaited()
    session.commit.assert_not_awaited()
