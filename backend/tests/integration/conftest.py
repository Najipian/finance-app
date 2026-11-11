"""Integration fixtures: real Postgres 16 + Redis 7 (testcontainers), real migrations.

One pair of containers is shared by the whole session. The schema is built by
running the Alembic migrations, so every run also tests the migrations. Tables
are truncated after each test.
"""

import os
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from finance_app.core.config import Environment, Settings
from finance_app.main import create_app

# On Windows with Docker Desktop, testcontainers can read the Ryuk reaper's port
# mapping before Docker publishes it ("Port mapping ... 8080 is not available").
# Our fixtures stop their containers via context managers, so Ryuk is not needed
# locally. CI runs on Linux and keeps Ryuk enabled.
if sys.platform == "win32":
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def integration_settings() -> Iterator[Settings]:
    """Settings pointing at freshly started Postgres and Redis containers."""
    with (
        PostgresContainer("postgres:16-alpine") as pg,
        RedisContainer("redis:7-alpine") as redis,
    ):
        redis_host, redis_port = redis.get_container_host_ip(), redis.get_exposed_port(6379)
        yield Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment=Environment.TEST,
            postgres_host=pg.get_container_host_ip(),
            postgres_port=int(pg.get_exposed_port(5432)),
            postgres_user=pg.username,
            postgres_password=SecretStr(pg.password),
            postgres_db=pg.dbname,
            redis_url=f"redis://{redis_host}:{redis_port}/0",
            jwt_secret=SecretStr("integration-test-jwt-secret-0123456789"),
        )


@pytest.fixture(scope="session")
def migrated_settings(integration_settings: Settings) -> Settings:
    """Run ``alembic upgrade head`` against the test database once per session."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = integration_settings.database_url
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return integration_settings


@asynccontextmanager
async def running_app(settings: Settings) -> AsyncIterator[AsyncClient]:
    """Run an app with its real lifespan; wipe DB rows and Redis keys afterwards."""
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        try:
            yield client
        finally:
            async with app.state.sessionmaker() as session:
                await session.execute(text("TRUNCATE users CASCADE"))
                await session.commit()
            await app.state.redis.flushdb()  # rate-limit counters


@pytest.fixture
async def api(migrated_settings: Settings) -> AsyncIterator[AsyncClient]:
    """HTTP client for an app running against the containers with default settings."""
    async with running_app(migrated_settings) as client:
        yield client
