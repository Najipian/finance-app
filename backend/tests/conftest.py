"""Shared fixtures. Tests never read the developer's real .env."""

import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

# Modules that call get_settings() at import time (the arq worker) need these.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-only")

from finance_app.core.config import Environment, Settings
from finance_app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=Environment.TEST,
        postgres_password=SecretStr("test-only"),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client calling the app in-process (lifespan not run; override deps)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
