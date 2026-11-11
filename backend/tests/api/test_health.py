from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from finance_app.api.deps import get_db, get_redis


class FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def execute(self, _statement: Any) -> None:
        if self.fail:
            raise ConnectionRefusedError("db down")


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def ping(self) -> bool:
        if self.fail:
            raise ConnectionRefusedError("redis down")
        return True


def _override(app: FastAPI, *, db_fails: bool = False, redis_fails: bool = False) -> None:
    async def fake_db() -> Any:
        yield FakeSession(fail=db_fails)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_redis] = lambda: FakeRedis(fail=redis_fails)


async def test_liveness_returns_ok_without_touching_dependencies(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_ok_when_database_and_redis_respond(
    app: FastAPI, client: AsyncClient
) -> None:
    _override(app)

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_readiness_503_when_database_unreachable(app: FastAPI, client: AsyncClient) -> None:
    _override(app, db_fails=True)

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "fail", "redis": "ok"}


async def test_readiness_503_when_redis_unreachable(app: FastAPI, client: AsyncClient) -> None:
    _override(app, redis_fails=True)

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


async def test_openapi_schema_is_published(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health/ready" in response.json()["paths"]
