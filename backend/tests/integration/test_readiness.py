"""Readiness against real Postgres 16 and Redis started by testcontainers."""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from finance_app.core.config import Environment, Settings
from finance_app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def real_settings() -> Iterator[Settings]:
    with (
        PostgresContainer("postgres:16-alpine") as pg,
        RedisContainer("redis:7-alpine") as redis,
    ):
        yield Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment=Environment.TEST,
            postgres_host=pg.get_container_host_ip(),
            postgres_port=int(pg.get_exposed_port(5432)),
            postgres_user=pg.username,
            postgres_password=SecretStr(pg.password),
            postgres_db=pg.dbname,
            redis_url=(f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"),
        )


async def test_readiness_ok_against_real_postgres_and_redis(real_settings: Settings) -> None:
    app = create_app(real_settings)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}
