from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import ActionExecution, Campaign, User


@pytest.fixture(autouse=True)
def override_action_dependencies():
    """替换动作接口的数据库和登录依赖。"""
    session = AsyncMock()

    async def session_override():
        """提供动作接口测试使用的异步会话。"""
        yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7,
        role="增长运营",
        status="启用",
    )
    yield session
    app.dependency_overrides.clear()


def make_action_record() -> ActionExecution:
    """构造动作列表接口使用的执行记录。

    Returns:
        一条可序列化的成功执行记录。
    """
    now = datetime(2026, 9, 6, 12)
    return ActionExecution(
        id=6,
        approval_id=4,
        suggestion_id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        action_type="pause",
        action_params={"ad_group_id": 32},
        before_state={"status": "已上线"},
        after_state={"status": "已暂停"},
        tool_name="pause_ad_group",
        tool_result={"status": "已暂停"},
        executor_id=7,
        status="成功",
        error_message=None,
        rollback_status="可回滚",
        executed_at=now,
        created_at=now,
    )


def test_action_list_returns_campaign_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证动作列表返回当前活动的执行记录。"""
    get_campaign = AsyncMock(
        return_value=Campaign(id=8, owner_id=7)
    )
    list_actions = AsyncMock(
        return_value=[make_action_record()]
    )
    monkeypatch.setattr(
        "app.api.v1.actions.get_campaign",
        get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.actions.list_action_executions",
        list_actions,
    )

    response = TestClient(app).get(
        "/api/v1/actions",
        params={"campaign_id": 8},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["id"] == 6
    assert data[0]["rollback_status"] == "可回滚"
    assert list_actions.await_args.args[1] == 8


def test_action_list_hides_inaccessible_campaign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证无活动权限时不查询动作执行记录。"""
    monkeypatch.setattr(
        "app.api.v1.actions.get_campaign",
        AsyncMock(return_value=None),
    )
    list_actions = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.actions.list_action_executions",
        list_actions,
    )

    response = TestClient(app).get(
        "/api/v1/actions",
        params={"campaign_id": 8},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "活动不存在"
    list_actions.assert_not_awaited()


def test_action_list_rejects_invalid_campaign_id() -> None:
    """验证活动编号必须是正整数。"""
    response = TestClient(app).get(
        "/api/v1/actions",
        params={"campaign_id": 0},
    )

    assert response.status_code == 422


def test_action_detail_returns_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    override_action_dependencies: AsyncMock,
) -> None:
    """验证动作详情返回执行前后状态快照。"""
    override_action_dependencies.get.return_value = (
        make_action_record()
    )
    monkeypatch.setattr(
        "app.api.v1.actions.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )

    response = TestClient(app).get(
        "/api/v1/actions/6"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 6
    assert data["before_state"] == {"status": "已上线"}
    assert data["after_state"] == {"status": "已暂停"}


def test_action_detail_returns_404_when_missing(
    override_action_dependencies: AsyncMock,
) -> None:
    """验证动作执行记录不存在时返回 404。"""
    override_action_dependencies.get.return_value = None

    response = TestClient(app).get(
        "/api/v1/actions/999"
    )

    assert response.status_code == 404
    assert response.json()["message"] == (
        "动作执行记录不存在"
    )


def test_action_detail_hides_inaccessible_campaign(
    monkeypatch: pytest.MonkeyPatch,
    override_action_dependencies: AsyncMock,
) -> None:
    """验证无活动权限时隐藏动作执行记录。"""
    override_action_dependencies.get.return_value = (
        make_action_record()
    )
    monkeypatch.setattr(
        "app.api.v1.actions.get_campaign",
        AsyncMock(return_value=None),
    )

    response = TestClient(app).get(
        "/api/v1/actions/6"
    )

    assert response.status_code == 404
    assert response.json()["message"] == (
        "动作执行记录不存在"
    )


def test_action_rollback_requires_manager() -> None:
    """验证非投放负责人不能触发动作回滚。"""
    rollback = AsyncMock()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "app.api.v1.actions.rollback_action",
        rollback,
    )

    try:
        response = TestClient(app).post(
            "/api/v1/actions/6/rollback"
        )
    finally:
        monkeypatch.undo()

    assert response.status_code == 403
    rollback.assert_not_awaited()


def test_action_rollback_returns_updated_record(
    monkeypatch: pytest.MonkeyPatch,
    override_action_dependencies: AsyncMock,
) -> None:
    """验证负责人回滚成功后获得更新后的执行记录。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )
    action = make_action_record()
    action.rollback_status = "已回滚"
    override_action_dependencies.get.return_value = action
    monkeypatch.setattr(
        "app.api.v1.actions.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    rollback = AsyncMock(return_value=action)
    monkeypatch.setattr(
        "app.api.v1.actions.rollback_action",
        rollback,
    )

    response = TestClient(app).post(
        "/api/v1/actions/6/rollback"
    )

    assert response.status_code == 200
    assert response.json()["data"]["rollback_status"] == (
        "已回滚"
    )
    assert rollback.await_args.args[1:] == (6, manager)


def test_action_rollback_returns_422_when_not_safe(
    monkeypatch: pytest.MonkeyPatch,
    override_action_dependencies: AsyncMock,
) -> None:
    """验证平台状态被改动时接口返回安全回滚错误。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )
    override_action_dependencies.get.return_value = (
        make_action_record()
    )
    monkeypatch.setattr(
        "app.api.v1.actions.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        "app.api.v1.actions.rollback_action",
        AsyncMock(
            side_effect=ValueError(
                "平台状态已被改动，需人工处理"
            )
        ),
    )

    response = TestClient(app).post(
        "/api/v1/actions/6/rollback"
    )

    assert response.status_code == 422
    assert response.json()["message"] == (
        "平台状态已被改动，需人工处理"
    )
