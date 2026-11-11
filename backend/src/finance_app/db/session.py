"""Async engine and session factories.

The app factory creates one engine per process at startup and stores it on
``app.state``; nothing here is a module-level global.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from finance_app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine for the configured Postgres database.

    Args:
        settings: Application settings providing ``database_url``.

    Returns:
        An ``AsyncEngine`` with pre-ping on, so stale pooled connections are replaced.
    """
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory used per request and per job.

    ``expire_on_commit=False`` keeps loaded attributes usable after commit, which
    async code needs because lazy refreshes would require an await.

    Args:
        engine: The engine sessions should bind to.

    Returns:
        A configured ``async_sessionmaker``.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
