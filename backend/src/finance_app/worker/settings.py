"""arq worker configuration and jobs.

Run with ``arq finance_app.worker.settings.WorkerSettings``. The worker owns its
own DB engine, provider client and cipher, built in ``startup`` from settings (or
from ``ctx["settings"]`` when tests start a worker with their own settings).
"""

import uuid
from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings

from finance_app.core.config import Settings, get_settings
from finance_app.core.crypto import TokenCipher
from finance_app.core.logging import configure_logging

# Register every ORM model in this process. The API imports them via its routes;
# the worker must do it itself, or foreign keys (e.g. bank_connections -> users)
# can't be resolved when a job first touches the database.
from finance_app.db import registry  # noqa: F401
from finance_app.db.session import create_engine, create_sessionmaker
from finance_app.modules.accounts.sync import AccountSyncService
from finance_app.providers.factory import build_provider, close_provider

log = structlog.get_logger(__name__)


async def ping(ctx: dict[str, Any]) -> str:
    """Trivial job used to check that the worker consumes the queue.

    Args:
        ctx: arq job context.

    Returns:
        The string ``"pong"``.
    """
    return "pong"


async def sync_accounts(ctx: dict[str, Any], connection_id: str) -> int:
    """Fetch a connection's accounts and balances from the provider (BR-02, BR-05).

    Args:
        ctx: arq job context with ``sessionmaker``, ``provider`` and ``cipher``.
        connection_id: The connection to sync, as a string UUID.

    Returns:
        Number of accounts synced.
    """
    async with ctx["sessionmaker"]() as session:
        service = AccountSyncService(session, ctx["provider"], ctx["cipher"])
        return await service.sync_connection(uuid.UUID(connection_id))


async def startup(ctx: dict[str, Any]) -> None:
    """Create the worker's DB engine, provider and cipher.

    Args:
        ctx: arq worker context; may already contain ``settings`` (tests).
    """
    settings: Settings = ctx.get("settings") or get_settings()
    configure_logging(settings)
    engine = create_engine(settings)
    ctx.update(
        settings=settings,
        engine=engine,
        sessionmaker=create_sessionmaker(engine),
        provider=build_provider(settings),
        cipher=TokenCipher(settings.encryption_keys(), settings.token_encryption_key_version),
    )
    log.info("worker_startup", bank_provider=ctx["provider"].name)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Close the provider client and DB engine.

    Args:
        ctx: arq worker context.
    """
    await close_provider(ctx["provider"])
    await ctx["engine"].dispose()


class WorkerSettings:
    """Settings object that the ``arq`` CLI reads."""

    functions: ClassVar[list[Any]] = [ping, sync_accounts]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
