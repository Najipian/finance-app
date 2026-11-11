"""Readiness checks against Postgres and Redis."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.health.schemas import CheckResult, ReadinessStatus

CHECK_TIMEOUT_SECONDS = 2.0

log = structlog.get_logger(__name__)


async def _run_check(name: str, check: Callable[[], Awaitable[object]]) -> CheckResult:
    """Run one check with a timeout; any failure counts as ``fail``.

    A readiness probe must answer, not raise, so every exception is caught here.
    Only the exception type is logged: messages can contain hostnames or DSNs.
    """
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await check()
    except Exception as exc:  # noqa: BLE001 - see docstring
        log.warning("readiness_check_failed", check=name, error_type=type(exc).__name__)
        return "fail"
    return "ok"


async def check_readiness(session: AsyncSession, redis: Redis) -> ReadinessStatus:
    """Check that Postgres and Redis both respond.

    Args:
        session: A database session to run ``SELECT 1`` on.
        redis: The Redis client to ``PING``.

    Returns:
        The overall status and the result of each check.
    """

    async def ping_database() -> None:
        await session.execute(text("SELECT 1"))

    async def ping_redis() -> None:
        await redis.ping()

    checks: dict[str, CheckResult] = {
        "database": await _run_check("database", ping_database),
        "redis": await _run_check("redis", ping_redis),
    }
    status: Literal["ok", "degraded"] = (
        "ok" if all(result == "ok" for result in checks.values()) else "degraded"
    )
    return ReadinessStatus(status=status, checks=checks)
