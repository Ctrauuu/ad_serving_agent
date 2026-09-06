from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import CaseLibrary, User


@pytest.fixture(autouse=True)
def override_dependencies():
    """为案例接口测试提供最小会话和已认证用户。"""
    async def session_override():
        yield object()

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7,
        role="投放人员",
        status="启用",
    )
    yield
    app.dependency_overrides.clear()


def test_case_list_returns_public_case_fields(monkeypatch) -> None:
    """验证案例列表返回业务字段且不暴露向量标识。"""
    case = CaseLibrary(
        id=8,
        case_type="anomaly",
        campaign_id=5,
        scene_desc="CPA 上升",
        anomaly_type="成本飙升",
        cause="素材疲劳",
        action="replace_creative",
        effectiveness="失败",
        conclusion="应提前更新素材",
        vector_id="8",
        created_at=datetime(2026, 9, 6, 12),
    )

    async def fake_list_cases(session, case_type):
        assert case_type is None
        return [case]

    monkeypatch.setattr(
        "app.api.v1.cases.list_review_cases",
        fake_list_cases,
    )

    response = TestClient(app).get("/api/v1/cases")

    assert response.status_code == 200
    assert response.json()["data"][0]["case_type"] == "anomaly"
    assert "vector_id" not in response.json()["data"][0]


def test_case_list_passes_type_filter(monkeypatch) -> None:
    """验证案例类型查询参数被传入服务层。"""
    async def fake_list_cases(session, case_type):
        assert case_type == "intervention"
        return []

    monkeypatch.setattr(
        "app.api.v1.cases.list_review_cases",
        fake_list_cases,
    )

    response = TestClient(app).get(
        "/api/v1/cases",
        params={"case_type": "intervention"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_case_list_rejects_unknown_type() -> None:
    """验证非约定案例类型会在请求边界被拒绝。"""
    response = TestClient(app).get(
        "/api/v1/cases",
        params={"case_type": "unknown"},
    )

    assert response.status_code == 422
