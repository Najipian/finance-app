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
from arq.connections import RedisSettings
from arq.worker import Worker
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Environment, Settings
from finance_app.db.session import create_engine, create_sessionmaker
from finance_app.main import create_app
from finance_app.worker.settings import revoke_consent, sync_connection
from finance_app.worker.settings import shutdown as worker_shutdown
from finance_app.worker.settings import startup as worker_startup

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


@pytest.fixture
async def db(migrated_settings: Settings) -> AsyncIterator[AsyncSession]:
    """A separate DB session for asserting on stored rows."""
    engine = create_engine(migrated_settings)
    async with create_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()


async def run_worker_burst(settings: Settings) -> None:
    """Run a real arq worker until the queue is empty, then stop."""
    worker = Worker(
        functions=[sync_connection, revoke_consent],
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        burst=True,
        on_startup=worker_startup,
        on_shutdown=worker_shutdown,
        ctx={"settings": settings},
        poll_delay=0.05,
        # arq's close() sends SIGUSR1 to itself when handle_signals=False, and Windows
        # has no SIGUSR1. With handlers enabled, arq skips them on Windows itself.
        handle_signals=sys.platform == "win32",
    )
    try:
        await worker.main()
    finally:
        await worker.close()
