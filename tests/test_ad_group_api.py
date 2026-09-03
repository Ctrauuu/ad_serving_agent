from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import Campaign, User


@pytest.fixture(autouse=True)
def override_dependencies():
    session = AsyncMock()

    async def session_override():
        yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        role="投放人员",
        status="启用",
    )
    yield
    app.dependency_overrides.clear()


def test_list_ad_groups_requires_visible_campaign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_campaign(*_):
        return None

    monkeypatch.setattr(
        "app.api.v1.ad_groups.get_campaign",
        fake_get_campaign,
    )

    response = TestClient(app).get(
        "/api/v1/ad-groups?campaign_id=8"
    )

    assert response.status_code == 404
    assert response.json()["message"] == "活动不存在"


def test_list_ad_groups_returns_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_campaign(*_):
        return Campaign(id=8)

    async def fake_list_ad_groups(*_):
        return []

    monkeypatch.setattr(
        "app.api.v1.ad_groups.get_campaign",
        fake_get_campaign,
    )
    monkeypatch.setattr(
        "app.api.v1.ad_groups.list_ad_groups",
        fake_list_ad_groups,
    )

    response = TestClient(app).get(
        "/api/v1/ad-groups?campaign_id=8"
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
