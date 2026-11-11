"""FastAPI dependencies shared by routes (database session, Redis, settings)."""

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_app.core.config import Settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for one request, closed afterwards.

    Args:
        request: The current request; the session factory lives on ``app.state``.

    Yields:
        An ``AsyncSession``. Services decide when to commit.
    """
    sessionmaker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with sessionmaker() as session:
        yield session


def get_redis(request: Request) -> Redis:
    """Return the app-wide Redis client created at startup.

    Args:
        request: The current request.

    Returns:
        The shared ``Redis`` client.
    """
    return cast(Redis, request.app.state.redis)


def get_app_settings(request: Request) -> Settings:
    """Return the settings the app was created with.

    Args:
        request: The current request.

    Returns:
        The ``Settings`` passed to ``create_app``.
    """
    return cast(Settings, request.app.state.settings)


DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
