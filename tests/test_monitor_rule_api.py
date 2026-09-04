from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.infrastructure.database import get_session
from app.main import app
from app.models import MonitorRule, User


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


def test_monitor_rule_list(monkeypatch) -> None:
    async def fake_list_monitor_rules(_):
        return [
            MonitorRule(
                id=1,
                name="CPA超目标1.5倍",
                rule_type="fixed_threshold",
                metric="cpa",
                condition_json={"multiple": 1.5},
                stage="稳态期",
                risk_level="高",
                enabled=True,
                created_at=datetime(2026, 9, 1),
                updated_at=datetime(2026, 9, 1),
            )
        ]

    monkeypatch.setattr(
        "app.api.v1.monitor_rules.list_monitor_rules",
        fake_list_monitor_rules,
    )

    response = TestClient(app).get(
        "/api/v1/monitor-rules"
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["metric"] == "cpa"
