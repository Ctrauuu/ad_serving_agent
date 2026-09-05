from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import Campaign, InterventionSuggestion, User
from app.schemas import (
    ApprovalDetail,
    ApprovalRecordRead,
    InterventionSuggestionRead,
)


@pytest.fixture(autouse=True)
def override_approval_dependencies():
    """替换审批接口的数据库和登录依赖。"""
    session = AsyncMock()

    async def session_override():
        """提供审批接口测试会话。"""
        yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7,
        role="增长运营",
        status="启用",
    )
    yield session
    app.dependency_overrides.clear()


def make_approval_suggestion() -> InterventionSuggestion:
    """构造提交审批接口测试使用的建议。"""
    now = datetime(2026, 9, 5, 12)
    return InterventionSuggestion(
        id=4,
        anomaly_id=4,
        campaign_id=8,
        target_type="ad_group",
        target_id=32,
        cause_id=8,
        action_type="extend_observation",
        action_params={"ad_group_id": 32},
        metric_evidence={"metric": "cost_rate"},
        risk_level="低",
        is_primary=True,
        status="待提交",
        created_at=now,
        updated_at=now,
    )


def make_approval_detail() -> ApprovalDetail:
    """构造提交审批接口的成功响应。"""
    now = datetime(2026, 9, 5, 12)
    suggestion = make_approval_suggestion()
    suggestion.status = "待执行"
    return ApprovalDetail(
        approval=ApprovalRecordRead(
            id=4,
            suggestion_id=4,
            campaign_id=8,
            risk_level="低",
            auto_execute=True,
            approver_id=None,
            approval_opinion="符合自动执行安全边界",
            reject_reason=None,
            status="已通过",
            approved_at=now,
            submitted_at=now,
        ),
        suggestion=(
            InterventionSuggestionRead.model_validate(
                suggestion
            )
        ),
    )


def test_submit_approval_returns_unified_result(
    monkeypatch: pytest.MonkeyPatch,
    override_approval_dependencies: AsyncMock,
) -> None:
    """验证提交审批接口返回风险分流结果。"""
    override_approval_dependencies.get.return_value = (
        make_approval_suggestion()
    )
    monkeypatch.setattr(
        "app.api.v1.approvals.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.approvals."
            "submit_suggestion_for_approval"
        ),
        AsyncMock(return_value=make_approval_detail()),
    )

    response = TestClient(app).post(
        "/api/v1/suggestions/4/submit-approval"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approval"]["status"] == "已通过"
    assert data["suggestion"]["status"] == "待执行"


def test_submit_approval_hides_inaccessible_suggestion(
    monkeypatch: pytest.MonkeyPatch,
    override_approval_dependencies: AsyncMock,
) -> None:
    """验证无权访问时不会调用提交审批服务。"""
    override_approval_dependencies.get.return_value = (
        make_approval_suggestion()
    )
    submit = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.approvals.get_campaign",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.approvals."
            "submit_suggestion_for_approval"
        ),
        submit,
    )

    response = TestClient(app).post(
        "/api/v1/suggestions/4/submit-approval"
    )

    assert response.status_code == 404
    submit.assert_not_awaited()


def test_submit_approval_returns_422_for_forbidden_action(
    monkeypatch: pytest.MonkeyPatch,
    override_approval_dependencies: AsyncMock,
) -> None:
    """验证禁止动作被接口转换为 422。"""
    override_approval_dependencies.get.return_value = (
        make_approval_suggestion()
    )
    monkeypatch.setattr(
        "app.api.v1.approvals.get_campaign",
        AsyncMock(return_value=Campaign(id=8, owner_id=7)),
    )
    monkeypatch.setattr(
        (
            "app.api.v1.approvals."
            "submit_suggestion_for_approval"
        ),
        AsyncMock(side_effect=ValueError("禁止提交执行")),
    )

    response = TestClient(app).post(
        "/api/v1/suggestions/4/submit-approval"
    )

    assert response.status_code == 422
    assert response.json()["message"] == "禁止提交执行"


def test_approval_list_passes_status_and_current_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批列表接口透传状态筛选和负责人身份。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )
    list_service = AsyncMock(
        return_value=[make_approval_detail()]
    )
    monkeypatch.setattr(
        "app.api.v1.approvals.list_approvals",
        list_service,
    )

    response = TestClient(app).get(
        "/api/v1/approvals",
        params={"status": "待审批"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["approval"]["id"] == 4
    call = list_service.await_args
    assert call.args[1] is manager
    assert call.kwargs["status_filter"] == "待审批"


def test_approval_list_rejects_invalid_status() -> None:
    """验证审批列表拒绝未定义的状态筛选值。"""
    response = TestClient(app).get(
        "/api/v1/approvals",
        params={"status": "处理中"},
    )

    assert response.status_code == 422


def test_approval_detail_returns_unified_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批详情接口返回审批及关联建议。"""
    detail_service = AsyncMock(
        return_value=make_approval_detail()
    )
    monkeypatch.setattr(
        "app.api.v1.approvals.get_approval_detail",
        detail_service,
    )

    response = TestClient(app).get(
        "/api/v1/approvals/4"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approval"]["id"] == 4
    assert data["suggestion"]["id"] == 4
    assert detail_service.await_args.args[1] == 4


def test_approval_detail_returns_404_when_inaccessible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证审批不存在或无权访问时统一返回 404。"""
    monkeypatch.setattr(
        "app.api.v1.approvals.get_approval_detail",
        AsyncMock(return_value=None),
    )

    response = TestClient(app).get(
        "/api/v1/approvals/999"
    )

    assert response.status_code == 404
    assert response.json()["message"] == "审批记录不存在"


def test_approval_approve_requires_manager_and_records_opinion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证负责人可以通过审批并提交审批意见。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )
    approve_service = AsyncMock(
        return_value=make_approval_detail()
    )
    monkeypatch.setattr(
        "app.api.v1.approvals.approve_approval",
        approve_service,
    )

    response = TestClient(app).post(
        "/api/v1/approvals/4/approve",
        json={"opinion": "同意执行"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["approval"][
        "status"
    ] == "已通过"
    call = approve_service.await_args
    assert call.args[1:] == (
        4,
        manager,
        "同意执行",
    )


def test_approval_approve_rejects_non_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证非投放负责人不能通过审批。"""
    approve_service = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.approvals.approve_approval",
        approve_service,
    )

    response = TestClient(app).post(
        "/api/v1/approvals/4/approve",
        json={"opinion": "同意执行"},
    )

    assert response.status_code == 403
    approve_service.assert_not_awaited()


def test_approval_approve_returns_422_for_processed_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证接口拒绝重复处理已经完成的审批。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )
    monkeypatch.setattr(
        "app.api.v1.approvals.approve_approval",
        AsyncMock(
            side_effect=ValueError(
                "当前审批状态不允许通过"
            )
        ),
    )

    response = TestClient(app).post(
        "/api/v1/approvals/4/approve",
        json={},
    )

    assert response.status_code == 422
    assert response.json()["message"] == (
        "当前审批状态不允许通过"
    )


def test_approval_reject_requires_manager_and_records_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证负责人可以驳回审批并提交驳回原因。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )
    detail = make_approval_detail()
    detail.approval.status = "已驳回"
    detail.approval.reject_reason = "证据不足"
    detail.suggestion.status = "已驳回"
    reject_service = AsyncMock(return_value=detail)
    monkeypatch.setattr(
        "app.api.v1.approvals.reject_approval",
        reject_service,
    )

    response = TestClient(app).post(
        "/api/v1/approvals/4/reject",
        json={"reason": "证据不足"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approval"]["status"] == "已驳回"
    assert data["approval"]["reject_reason"] == "证据不足"
    call = reject_service.await_args
    assert call.args[1:] == (
        4,
        manager,
        "证据不足",
    )


def test_approval_reject_rejects_non_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证非投放负责人不能驳回审批。"""
    reject_service = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.approvals.reject_approval",
        reject_service,
    )

    response = TestClient(app).post(
        "/api/v1/approvals/4/reject",
        json={"reason": "证据不足"},
    )

    assert response.status_code == 403
    reject_service.assert_not_awaited()


def test_approval_reject_requires_nonblank_reason() -> None:
    """验证驳回接口拒绝空白原因。"""
    manager = User(
        id=3,
        role="投放负责人",
        status="启用",
    )
    app.dependency_overrides[get_current_user] = (
        lambda: manager
    )

    response = TestClient(app).post(
        "/api/v1/approvals/4/reject",
        json={"reason": ""},
    )

    assert response.status_code == 422
