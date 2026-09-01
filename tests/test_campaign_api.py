from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from app.schemas import GoalParseResult, StructuredGoal
from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import Campaign, User


def make_campaign() -> Campaign:
    return Campaign(
        id=8,
        name="新品推广",
        product_id=1,
        owner_id=7,
        budget_total=Decimal("80000.00"),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        conversion_goal="线索",
        goal_text="预算8万获取高质量线索",
        structured_goal=None,
        risk_limit=None,
        status="草稿",
        created_at=datetime(2026, 9, 1),
        updated_at=datetime(2026, 9, 1),
    )


@pytest.fixture(autouse=True)
def override_dependencies():
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


def test_create_campaign_returns_unified_response(monkeypatch) -> None:
    async def fake_create_campaign(session, form, owner_id):
        assert owner_id == 7
        return make_campaign()

    monkeypatch.setattr(
        "app.api.v1.campaigns.create_campaign",
        fake_create_campaign,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns",
        json={
            "name": "新品推广",
            "product_id": 1,
            "budget": "80000.00",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "conversion_goal": "线索",
            "goal_text": "预算8万获取高质量线索",
        },
    )

    assert response.status_code == 201
    assert response.json()["code"] == 0
    assert response.json()["data"]["name"] == "新品推广"
    assert response.json()["data"]["status"] == "草稿"


def test_missing_campaign_returns_404(monkeypatch) -> None:
    async def fake_get_campaign(session, campaign_id, current_user):
        return None

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )

    response = TestClient(app).get("/api/v1/campaigns/999")

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "活动不存在",
        "data": None,
    }

def test_parse_goal_returns_missing_fields(monkeypatch) -> None:
    async def fake_get_campaign(session, campaign_id, current_user):
        return make_campaign()

    async def fake_parse_goal_text(goal_text):
        return GoalParseResult(
            missing_fields=["audience", "cycle", "risk"]
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.parse_goal_text",
        fake_parse_goal_text,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/parse-goal"
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": 422,
        "message": "目标信息不完整",
        "data": {
            "missing_fields": ["audience", "cycle", "risk"]
        },
    }


def test_parse_goal_returns_structured_result(monkeypatch) -> None:
    async def fake_get_campaign(session, campaign_id, current_user):
        return make_campaign()

    async def fake_parse_goal_text(goal_text):
        return GoalParseResult(
            structured_goal=StructuredGoal(
                product="企业HR系统",
                audience="企业HR负责人",
                budget=Decimal("80000.00"),
                cycle="2026-09-01 至 2026-09-30",
                conversion_goal="线索",
                channels=["信息流", "搜索广告"],
                risk="单条线索成本不超过300元",
            )
        )

    monkeypatch.setattr(
        "app.api.v1.campaigns.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.campaigns.parse_goal_text",
        fake_parse_goal_text,
    )

    response = TestClient(app).post(
        "/api/v1/campaigns/8/parse-goal"
    )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert (
        response.json()["data"]["structured_goal"]["product"]
        == "企业HR系统"
    )
    assert response.json()["data"]["missing_fields"] == []

def test_confirm_goal_returns_updated_campaign(monkeypatch) -> None:
    async def fake_update_campaign(
        session,
        campaign_id,
        form,
        current_user,
    ):
        campaign = make_campaign()
        campaign.structured_goal = form.structured_goal.model_dump(mode="json")
        campaign.status = "目标已结构化"
        return campaign

    monkeypatch.setattr(
        "app.api.v1.campaigns.update_campaign",
        fake_update_campaign,
    )

    response = TestClient(app).put(
        "/api/v1/campaigns/8",
        json={
            "structured_goal": {
                "product": "企业HR系统",
                "audience": "企业HR负责人",
                "budget": 80000,
                "cycle": "2026年9月",
                "conversion_goal": "线索",
                "channels": ["信息流"],
                "risk": "单条线索成本不超过300元",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "目标已结构化"
    assert (
        response.json()["data"]["structured_goal"]["product"]
        == "企业HR系统"
    )


def test_only_investor_can_confirm_goal() -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=3,
        role="投放负责人",
        status="启用",
    )

    response = TestClient(app).put(
        "/api/v1/campaigns/8",
        json={
            "structured_goal": {
                "product": "企业HR系统",
                "audience": "企业HR负责人",
                "budget": 80000,
                "cycle": "2026年9月",
                "conversion_goal": "线索",
                "channels": ["信息流"],
                "risk": "单条线索成本不超过300元",
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["message"] == "仅投放人员可以确认结构化目标"