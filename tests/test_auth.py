from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user, require_role
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.security import hash_password
from app.infrastructure.database import get_session
from app.main import app
from app.models.user import User

PASSWORD = "correct-password"
PASSWORD_HASH = hash_password(PASSWORD)


class FakeSession:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def scalar(self, _) -> User | None:
        return self.user

    async def get(self, _, user_id: int) -> User | None:
        if self.user is None or self.user.id != user_id:
            return None
        return self.user


def make_user(
    *,
    role: str = "投放负责人",
    status: str = "启用",
) -> User:
    return User(
        id=1,
        username="leader",
        password_hash=PASSWORD_HASH,
        display_name="负责人",
        role=role,
        status=status,
    )


def use_session(user: User | None) -> None:
    async def override_session():
        yield FakeSession(user)

    app.dependency_overrides[get_session] = override_session


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


def test_login_and_current_user() -> None:
    use_session(make_user())
    client = TestClient(app)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "leader", "password": PASSWORD},
    )

    assert login.status_code == 200
    assert login.json()["data"]["user"] == {
        "id": 1,
        "username": "leader",
        "display_name": "负责人",
        "role": "投放负责人",
    }

    token = login.json()["data"]["token"]
    current_user = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert current_user.status_code == 200
    assert current_user.json()["data"]["username"] == "leader"


def test_unknown_user_cannot_login() -> None:
    use_session(None)
    response = TestClient(app).post(
        "/api/v1/auth/login",
        json={"username": "missing", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"code": 401, "message": "用户名或密码错误", "data": None}


def test_wrong_password_cannot_login() -> None:
    use_session(make_user())
    response = TestClient(app).post(
        "/api/v1/auth/login",
        json={"username": "leader", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 401


def test_me_requires_token() -> None:
    response = TestClient(app).get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == 401


def test_expired_token_is_rejected() -> None:
    user = make_user()
    use_session(user)
    settings = get_settings()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role,
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    response = TestClient(app).get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == 401


@pytest.mark.parametrize(
    "user",
    [
        make_user(status="禁用"),
        make_user(role="增长运营"),
    ],
)
def test_disabled_user_or_changed_role_is_rejected(user: User) -> None:
    use_session(user)
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": "投放负责人",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    response = TestClient(app).get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [("投放负责人", 200), ("增长运营", 403)],
)
def test_leader_role_is_required(role: str, expected_status: int) -> None:
    role_app = FastAPI()
    register_exception_handlers(role_app)

    @role_app.get("/leader-only")
    async def leader_only(
        _: Annotated[User, Depends(require_role("投放负责人"))],
    ) -> dict[str, bool]:
        return {"ok": True}

    role_app.dependency_overrides[get_current_user] = lambda: make_user(role=role)
    response = TestClient(role_app).get("/leader-only")

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json() == {"code": 403, "message": "权限不足", "data": None}
