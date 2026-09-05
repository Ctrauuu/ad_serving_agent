import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.redis import redis_client
from app.models import ApprovalRecord, InterventionSuggestion, User
from app.services.approval import (
    approve_approval,
    create_approval_session,
    decide_approval_route,
    delete_approval_session,
    expire_pending_approvals,
    get_approval_detail,
    get_approval_session,
    list_approvals,
    reject_approval,
    submit_suggestion_for_approval,
)


def make_suggestion(
    action_type: str,
    params: dict[str, Any] | None = None,
    risk_level: str = "中",
    target_type: str = "ad_group",
) -> InterventionSuggestion:
    """构造风险路由测试使用的干预建议。

    Args:
        action_type: 干预动作类型。
        params: 动作参数。
        risk_level: 已计算的风险等级。
        target_type: 干预目标类型。

    Returns:
        可供风险路由判断的建议对象。
    """
    return InterventionSuggestion(
        action_type=action_type,
        action_params=params or {},
        risk_level=risk_level,
        target_type=target_type,
    )


@pytest.mark.parametrize(
    ("suggestion", "expected"),
    [
        (
            make_suggestion(
                "extend_observation",
                risk_level="低",
            ),
            "auto_execute",
        ),
        (
            make_suggestion("pause", risk_level="高"),
            "requires_approval",
        ),
        (
            make_suggestion(
                "pause",
                {"scope": "campaign"},
                risk_level="高",
                target_type="campaign",
            ),
            "forbidden",
        ),
        (
            make_suggestion(
                "adjust_budget",
                {
                    "scope": "campaign",
                    "direction": "increase",
                    "change_pct": "21%",
                },
                risk_level="高",
            ),
            "forbidden",
        ),
        (
            make_suggestion(
                "replace_creative",
                {"new_creative_id": 3},
            ),
            "auto_execute",
        ),
        (
            make_suggestion("replace_creative"),
            "requires_approval",
        ),
        (
            make_suggestion(
                "narrow_audience",
                {"narrow_pct": 10},
            ),
            "auto_execute",
        ),
        (
            make_suggestion(
                "narrow_audience",
                {"narrow_pct": "10.1"},
            ),
            "requires_approval",
        ),
        (
            make_suggestion("unknown_action"),
            "forbidden",
        ),
        (
            make_suggestion(
                "extend_observation",
                risk_level="高",
            ),
            "requires_approval",
        ),
    ],
)
def test_decide_approval_route(
    suggestion: InterventionSuggestion,
    expected: str,
) -> None:
    """验证动作、范围、比例和风险共同决定审批路线。"""
    assert decide_approval_route(suggestion) == expected


@pytest.mark.asyncio
async def test_approval_session_uses_72_hour_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批会话可以写入、读取并删除。"""
    set_value = AsyncMock()
    get_value = AsyncMock()
    delete_value = AsyncMock()
    monkeypatch.setattr(redis_client, "set", set_value)
    monkeypatch.setattr(redis_client, "get", get_value)
    monkeypatch.setattr(redis_client, "delete", delete_value)
    approval = ApprovalRecord(
        id=9,
        suggestion_id=4,
        campaign_id=8,
        risk_level="高",
        auto_execute=False,
        status="待审批",
    )

    payload = await create_approval_session(approval)

    assert payload["thread_id"] == "campaign:8:approval:9"
    set_args = set_value.await_args
    assert set_args.args[0] == "approval:session:9"
    assert set_args.kwargs["ex"] == 72 * 60 * 60
    get_value.return_value = set_args.args[1]

    saved = await get_approval_session(9)

    assert saved is not None
    assert json.loads(set_args.args[1])["status"] == "待审批"
    assert saved["suggestion_id"] == 4

    await delete_approval_session(9)
    delete_value.assert_awaited_once_with("approval:session:9")


def make_submit_suggestion(
    action_type: str,
    risk_level: str,
    params: dict[str, Any] | None = None,
) -> InterventionSuggestion:
    """构造提交审批测试使用的完整建议。

    Args:
        action_type: 干预动作类型。
        risk_level: 建议风险等级。
        params: 动作参数。

    Returns:
        包含响应转换所需字段的待提交建议。
    """
    now = datetime(2026, 9, 5, 12)
    return InterventionSuggestion(
        id=4,
        anomaly_id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        cause_id=8,
        action_type=action_type,
        action_params=params or {"ad_group_id": 32},
        metric_evidence={"metric": "cost_rate"},
        triggered_rule="消耗速度过快",
        expected_impact={"effect": "控制风险"},
        risk_notes="可能影响线索量",
        risk_level=risk_level,
        is_primary=True,
        status="待提交",
        created_at=now,
        updated_at=now,
    )


def make_submit_session(
    suggestion: InterventionSuggestion,
) -> AsyncMock:
    """构造能为审批记录补充数据库字段的会话。

    Args:
        suggestion: 查询返回的待提交建议。

    Returns:
        配置完成的异步数据库会话替身。
    """
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = suggestion

    async def fake_flush() -> None:
        """模拟数据库为审批记录生成主键和提交时间。"""
        approval = session.add.call_args.args[0]
        approval.id = 10
        approval.submitted_at = datetime(2026, 9, 5, 12)

    session.flush.side_effect = fake_flush
    return session


@pytest.mark.asyncio
async def test_submit_low_risk_auto_approves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证低风险建议直接获得执行许可。"""
    suggestion = make_submit_suggestion(
        "extend_observation",
        "低",
    )
    session = make_submit_session(suggestion)
    create_session = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.create_approval_session",
        create_session,
    )
    start_workflow = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.start_approval_workflow",
        start_workflow,
    )

    result = await submit_suggestion_for_approval(
        session,
        suggestion.id,
    )

    assert result is not None
    assert result.approval.status == "已通过"
    assert result.approval.auto_execute is True
    assert result.suggestion.status == "待执行"
    create_session.assert_not_awaited()
    start_workflow.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_high_risk_creates_pending_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证高风险建议进入人工审批并创建 Redis 会话。"""
    suggestion = make_submit_suggestion("pause", "高")
    session = make_submit_session(suggestion)
    create_session = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.create_approval_session",
        create_session,
    )
    start_workflow = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.start_approval_workflow",
        start_workflow,
    )

    result = await submit_suggestion_for_approval(
        session,
        suggestion.id,
    )

    assert result is not None
    assert result.approval.status == "待审批"
    assert result.suggestion.status == "审批中"
    approval = session.add.call_args.args[0]
    create_session.assert_awaited_once_with(approval)
    workflow_state = start_workflow.await_args.args[0]
    assert workflow_state["approval_id"] == approval.id
    assert workflow_state["suggestion_id"] == suggestion.id
    assert workflow_state["decision"] == "pending"


@pytest.mark.asyncio
async def test_submit_forbidden_action_does_not_write() -> None:
    """验证禁止动作不会创建审批记录。"""
    suggestion = make_submit_suggestion(
        "pause",
        "高",
        {"scope": "campaign"},
    )
    suggestion.target_type = "campaign"
    session = make_submit_session(suggestion)

    with pytest.raises(ValueError, match="禁止提交执行"):
        await submit_suggestion_for_approval(
            session,
            suggestion.id,
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_rolls_back_when_redis_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批会话创建失败时数据库回滚并清理 Redis。"""
    suggestion = make_submit_suggestion("pause", "高")
    session = make_submit_session(suggestion)
    monkeypatch.setattr(
        "app.services.approval.create_approval_session",
        AsyncMock(side_effect=RuntimeError("Redis 不可用")),
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.delete_approval_session",
        cleanup,
    )

    with pytest.raises(RuntimeError, match="Redis 不可用"):
        await submit_suggestion_for_approval(
            session,
            suggestion.id,
        )

    session.rollback.assert_awaited_once()
    cleanup.assert_awaited_once_with(10)


@pytest.mark.asyncio
async def test_submit_rolls_back_when_workflow_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批图启动失败时回滚数据库并清理会话。"""
    suggestion = make_submit_suggestion("pause", "高")
    session = make_submit_session(suggestion)
    monkeypatch.setattr(
        "app.services.approval.create_approval_session",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.approval.start_approval_workflow",
        AsyncMock(side_effect=RuntimeError("工作流启动失败")),
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.delete_approval_session",
        cleanup,
    )

    with pytest.raises(RuntimeError, match="工作流启动失败"):
        await submit_suggestion_for_approval(
            session,
            suggestion.id,
        )

    session.rollback.assert_awaited_once()
    cleanup.assert_awaited_once_with(10)


@pytest.mark.asyncio
async def test_list_approvals_combines_records_and_applies_filters() -> None:
    """验证审批列表组合建议并应用用户与状态过滤。"""
    suggestion = make_submit_suggestion("pause", "高")
    approval = ApprovalRecord(
        id=10,
        suggestion_id=suggestion.id,
        campaign_id=suggestion.campaign_id,
        risk_level="高",
        auto_execute=False,
        status="待审批",
        submitted_at=datetime(2026, 9, 5, 12),
    )
    session = AsyncMock(spec=AsyncSession)
    query_result = MagicMock()
    query_result.all.return_value = [
        (approval, suggestion)
    ]
    session.execute.return_value = query_result
    user = User(id=7, role="增长运营", status="启用")

    details = await list_approvals(
        session,
        user,
        status_filter="待审批",
    )

    assert details[0].approval.id == approval.id
    assert details[0].suggestion.id == suggestion.id
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "approval_record.status" in sql
    assert "campaign.owner_id" in sql


@pytest.mark.asyncio
async def test_list_approvals_manager_sees_all_campaigns() -> None:
    """验证投放负责人查询时不添加活动 owner 过滤。"""
    session = AsyncMock(spec=AsyncSession)
    query_result = MagicMock()
    query_result.all.return_value = []
    session.execute.return_value = query_result
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    await list_approvals(session, manager)

    statement = session.execute.await_args.args[0]
    assert "campaign.owner_id" not in str(statement)


@pytest.mark.asyncio
async def test_get_approval_detail_applies_owner_filter() -> None:
    """验证普通用户只能查询自己活动下的审批详情。"""
    suggestion = make_submit_suggestion("pause", "高")
    approval = ApprovalRecord(
        id=10,
        suggestion_id=suggestion.id,
        campaign_id=suggestion.campaign_id,
        risk_level="高",
        auto_execute=False,
        status="待审批",
        submitted_at=datetime(2026, 9, 5, 12),
    )
    session = AsyncMock(spec=AsyncSession)
    query_result = MagicMock()
    query_result.first.return_value = (
        approval,
        suggestion,
    )
    session.execute.return_value = query_result
    user = User(id=7, role="增长运营", status="启用")

    detail = await get_approval_detail(
        session,
        approval.id,
        user,
    )

    assert detail is not None
    assert detail.approval.id == approval.id
    assert detail.suggestion.id == suggestion.id
    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "approval_record.id" in sql
    assert "campaign.owner_id" in sql


@pytest.mark.asyncio
async def test_get_approval_detail_returns_none_when_missing() -> None:
    """验证审批记录不存在或不可访问时返回 None。"""
    session = AsyncMock(spec=AsyncSession)
    query_result = MagicMock()
    query_result.first.return_value = None
    session.execute.return_value = query_result
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    detail = await get_approval_detail(
        session,
        999,
        manager,
    )

    assert detail is None
    statement = session.execute.await_args.args[0]
    assert "campaign.owner_id" not in str(statement)


@pytest.mark.asyncio
async def test_approve_approval_records_audit_and_unlocks_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证人工通过后记录留痕并将建议置为待执行。"""
    suggestion = make_submit_suggestion("pause", "高")
    suggestion.status = "审批中"
    approval = ApprovalRecord(
        id=10,
        suggestion_id=suggestion.id,
        campaign_id=suggestion.campaign_id,
        risk_level="高",
        auto_execute=False,
        status="待审批",
        submitted_at=datetime(2026, 9, 5, 12),
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = approval
    session.get.return_value = suggestion
    resume_workflow = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.resume_approval_workflow",
        resume_workflow,
    )
    delete_session = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.delete_approval_session",
        delete_session,
    )
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    detail = await approve_approval(
        session,
        approval.id,
        manager,
        "  指标证据充分，同意执行  ",
    )

    assert detail is not None
    assert detail.approval.status == "已通过"
    assert detail.approval.approver_id == manager.id
    assert detail.approval.approval_opinion == (
        "指标证据充分，同意执行"
    )
    assert detail.suggestion.status == "待执行"
    assert "FOR UPDATE" in str(
        session.scalar.await_args.args[0]
    )
    session.commit.assert_awaited_once()
    resume_workflow.assert_awaited_once_with(
        campaign_id=approval.campaign_id,
        approval_id=approval.id,
        approved=True,
        approver_id=manager.id,
        opinion="指标证据充分，同意执行",
    )
    delete_session.assert_awaited_once_with(approval.id)


@pytest.mark.asyncio
async def test_approve_approval_rejects_processed_record() -> None:
    """验证已经完成的审批不能被重复通过。"""
    approval = ApprovalRecord(
        id=10,
        suggestion_id=4,
        campaign_id=8,
        risk_level="高",
        auto_execute=False,
        status="已驳回",
        submitted_at=datetime(2026, 9, 5, 12),
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = approval
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    with pytest.raises(ValueError, match="状态不允许通过"):
        await approve_approval(
            session,
            approval.id,
            manager,
        )

    session.get.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_approval_records_reason_and_rejects_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证人工驳回后记录原因并同步建议状态。"""
    suggestion = make_submit_suggestion("pause", "高")
    suggestion.status = "审批中"
    approval = ApprovalRecord(
        id=10,
        suggestion_id=suggestion.id,
        campaign_id=suggestion.campaign_id,
        risk_level="高",
        auto_execute=False,
        status="待审批",
        submitted_at=datetime(2026, 9, 5, 12),
    )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = approval
    session.get.return_value = suggestion
    resume_workflow = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.resume_approval_workflow",
        resume_workflow,
    )
    delete_session = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.delete_approval_session",
        delete_session,
    )
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    detail = await reject_approval(
        session,
        approval.id,
        manager,
        "  当前证据不足  ",
    )

    assert detail is not None
    assert detail.approval.status == "已驳回"
    assert detail.approval.approver_id == manager.id
    assert detail.approval.reject_reason == "当前证据不足"
    assert detail.approval.approved_at is not None
    assert detail.suggestion.status == "已驳回"
    assert "FOR UPDATE" in str(
        session.scalar.await_args.args[0]
    )
    session.commit.assert_awaited_once()
    resume_workflow.assert_awaited_once_with(
        campaign_id=approval.campaign_id,
        approval_id=approval.id,
        approved=False,
        approver_id=manager.id,
        reason="当前证据不足",
    )
    delete_session.assert_awaited_once_with(approval.id)


@pytest.mark.asyncio
async def test_reject_approval_requires_nonblank_reason() -> None:
    """验证空白驳回原因不会访问或修改数据库。"""
    session = AsyncMock(spec=AsyncSession)
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    with pytest.raises(ValueError, match="驳回原因不能为空"):
        await reject_approval(
            session,
            10,
            manager,
            "   ",
        )

    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_expire_pending_approvals_never_unlocks_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证超时审批和建议被终止且不会获得执行许可。"""
    current_time = datetime(2026, 9, 5, 12)
    approval = ApprovalRecord(
        id=10,
        suggestion_id=4,
        campaign_id=8,
        risk_level="高",
        auto_execute=False,
        status="待审批",
        submitted_at=datetime(2026, 9, 2, 11),
    )
    suggestion = make_submit_suggestion("pause", "高")
    suggestion.status = "审批中"
    session = AsyncMock(spec=AsyncSession)
    scalar_result = MagicMock()
    scalar_result.all.return_value = [approval]
    session.scalars.return_value = scalar_result
    session.get.return_value = suggestion
    delete_session = AsyncMock()
    monkeypatch.setattr(
        "app.services.approval.delete_approval_session",
        delete_session,
    )

    expired_ids = await expire_pending_approvals(
        session,
        now=current_time,
    )

    assert expired_ids == [approval.id]
    assert approval.status == "已超时"
    assert approval.auto_execute is False
    assert approval.approved_at == current_time
    assert suggestion.status == "审批超时"
    statement = session.scalars.await_args.args[0]
    sql = str(statement)
    assert "approval_record.submitted_at" in sql
    assert "FOR UPDATE" in sql
    assert statement._for_update_arg is not None
    assert statement._for_update_arg.skip_locked is True
    session.commit.assert_awaited_once()
    delete_session.assert_awaited_once_with(approval.id)


@pytest.mark.asyncio
async def test_expire_pending_approvals_skips_when_none_due() -> None:
    """验证没有到期审批时不提交数据库事务。"""
    session = AsyncMock(spec=AsyncSession)
    scalar_result = MagicMock()
    scalar_result.all.return_value = []
    session.scalars.return_value = scalar_result

    expired_ids = await expire_pending_approvals(session)

    assert expired_ids == []
    session.get.assert_not_awaited()
    session.commit.assert_not_awaited()
