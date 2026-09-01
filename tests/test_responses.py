from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.responses import error
from app.main import app


async def _ok() -> None:
    return None


def test_health_response_is_unified(monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.health.check_database", _ok)
    monkeypatch.setattr("app.api.v1.health.redis_client.ping", _ok)
    monkeypatch.setattr("app.api.v1.health.milvus_client.check", lambda: None)
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.json() == {
        "code": 0,
        "message": "ok",
        "data": {"status": "up", "dependencies": {"mysql": "up", "redis": "up", "milvus": "up"}},
    }


def test_unavailable_dependency_is_unified(monkeypatch) -> None:
    async def unavailable() -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.api.v1.health.check_database", unavailable)
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"code": 503, "message": "dependency unavailable: connection refused", "data": None}


def test_http_exception_is_unified() -> None:
    test_app = FastAPI()

    @test_app.exception_handler(HTTPException)
    async def exception_handler(_, exc: HTTPException):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content=error(exc.status_code, str(exc.detail)))

    @test_app.get("/error")
    async def raises_error() -> None:
        raise HTTPException(status_code=400, detail="bad request")

    response = TestClient(test_app).get("/error")
    assert response.json() == {"code": 400, "message": "bad request", "data": None}
