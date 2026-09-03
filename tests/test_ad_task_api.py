from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import User


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
    yield session
    app.dependency_overrides.clear()


def test_missing_ad_task_returns_404(
    override_dependencies,
) -> None:
    override_dependencies.get.return_value = None

    response = TestClient(app).get(
        "/api/v1/ad-tasks/999/status"
    )

    assert response.status_code == 404
    assert response.json()["message"] == "广告任务不存在"
