"""Readiness against real Postgres 16 and Redis started by testcontainers."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_readiness_ok_against_real_postgres_and_redis(api: AsyncClient) -> None:
    response = await api.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}
