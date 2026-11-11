"""arq worker: background jobs and schedules.

Run with ``arq finance_app.worker.settings.WorkerSettings``. The worker owns its own
DB engine, provider client, cipher and job queue, built in ``startup`` from settings
(or from ``ctx["settings"]`` when tests start a worker with their own settings).

Jobs (technical design, "Background jobs and sync"):

- ``sync_connection``: accounts, balances, transactions. Transient provider errors
  are retried with exponential backoff (30 s, 60 s, 120 s, 240 s); after the last
  try the connection shows ``failed`` (NFR-07).
- ``revoke_consent``: revoke at the provider after a disconnect, retried.
- ``schedule_syncs`` (cron, every 6 hours) and ``check_consent_expiry`` (cron,
  daily 06:00 UTC).
"""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from arq.worker import Retry

from finance_app.core.config import Settings, get_settings
from finance_app.core.crypto import TokenCipher
from finance_app.core.jobs import SCHEDULED_SYNC_WINDOW_SECONDS, ArqJobQueue
from finance_app.core.logging import configure_logging

# Register every ORM model in this process. The API imports them via its routes;
# the worker must do it itself, or foreign keys (e.g. bank_connections -> users)
# can't be resolved when a job first touches the database.
from finance_app.db import registry  # noqa: F401
from finance_app.db.session import create_engine, create_sessionmaker
from finance_app.modules.connections.lifecycle import ConsentLifecycleService
from finance_app.modules.connections.sync import ConnectionSyncService
from finance_app.providers.base import ProviderError
from finance_app.providers.factory import build_provider, close_provider

MAX_TRIES = 5
RETRY_BASE_SECONDS = 30

log = structlog.get_logger(__name__)


def retry_delay(job_try: int) -> int:
    """Exponential backoff: 30 s, 60 s, 120 s, 240 s for tries 1..4."""
    return int(RETRY_BASE_SECONDS * 2 ** (job_try - 1))


async def ping(ctx: dict[str, Any]) -> str:
    """Trivial job used to check that the worker consumes the queue.

    Args:
        ctx: arq job context.

    Returns:
        The string ``"pong"``.
    """
    return "pong"


async def sync_connection(ctx: dict[str, Any], connection_id: str) -> dict[str, int] | None:
    """Sync one connection (BR-05, BR-06); retry transient provider failures.

    Args:
        ctx: arq job context (``sessionmaker``, ``provider``, ``cipher``, ``job_try``).
        connection_id: The connection to sync, as a string UUID.

    Returns:
        Counts of what changed, or None if skipped or failed for good.

    Raises:
        Retry: After a transient failure, while tries remain.
    """
    job_try: int = ctx.get("job_try", 1)
    async with ctx["sessionmaker"]() as session:
        service = ConnectionSyncService(session, ctx["provider"], ctx["cipher"])
        try:
            result = await service.sync(uuid.UUID(connection_id))
        except ProviderError as exc:
            final = job_try >= ctx.get("max_tries", MAX_TRIES)
            await service.record_failure(uuid.UUID(connection_id), final=final)
            log.warning(
                "sync_failed",
                connection_id=connection_id,
                job_try=job_try,
                final=final,
                error=str(exc),
            )
            if final:
                return None
            raise Retry(defer=retry_delay(job_try)) from exc
    if result is None:
        return None
    return {
        "accounts": result.accounts,
        "transactions": result.transactions,
        "stale_pending_removed": result.stale_pending_removed,
    }


async def revoke_consent(ctx: dict[str, Any], provider_name: str, consent_id: str) -> bool:
    """Revoke a consent at the provider after a disconnect (BR-04), with retries.

    Args:
        ctx: arq job context.
        provider_name: Provider the consent belongs to.
        consent_id: Provider consent ID (not a secret).

    Returns:
        True if revoked; False if it can't be (provider no longer configured, or
        retries exhausted: the consent then lapses at its expiry).

    Raises:
        Retry: After a transient failure, while tries remain.
    """
    provider = ctx["provider"]
    if provider.name != provider_name:
        log.warning("revoke_skipped_other_provider", provider=provider_name)
        return False
    job_try: int = ctx.get("job_try", 1)
    try:
        await provider.revoke_consent(consent_id)
    except ProviderError as exc:
        if job_try >= ctx.get("max_tries", MAX_TRIES):
            log.error("revoke_failed", provider=provider_name, error=str(exc))
            return False
        raise Retry(defer=retry_delay(job_try)) from exc
    log.info("consent_revoked", provider=provider_name)
    return True


async def schedule_syncs(ctx: dict[str, Any]) -> int:
    """Queue a sync for every active connection (cron, every 6 hours).

    Returns:
        Number of syncs queued.
    """
    async with ctx["sessionmaker"]() as session:
        ids = await ConsentLifecycleService(session).active_connection_ids()
    queued = 0
    for connection_id in ids:
        if await ctx["job_queue"].enqueue_sync(
            connection_id, window_seconds=SCHEDULED_SYNC_WINDOW_SECONDS
        ):
            queued += 1
    log.info("syncs_scheduled", queued=queued, active=len(ids))
    return queued


async def check_consent_expiry(ctx: dict[str, Any]) -> dict[str, int]:
    """Mark expired consents ``needs_renewal`` (cron, daily 06:00 UTC; BR-03).

    Returns:
        Counts of consents expired now and expiring within 7 days.
    """
    async with ctx["sessionmaker"]() as session:
        report = await ConsentLifecycleService(session).check_expiry(datetime.now(UTC))
    log.info("consent_expiry_checked", expired=report.expired, expiring_soon=report.expiring_soon)
    return {"expired": report.expired, "expiring_soon": report.expiring_soon}


async def startup(ctx: dict[str, Any]) -> None:
    """Create the worker's DB engine, provider, cipher and job queue.

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
        job_queue=ArqJobQueue(ctx["redis"]),
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

    functions: ClassVar[list[Any]] = [ping, sync_connection, revoke_consent]
    cron_jobs: ClassVar[list[Any]] = [
        cron(schedule_syncs, hour={0, 6, 12, 18}, minute=0, unique=True),
        cron(check_consent_expiry, hour=6, minute=0, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = MAX_TRIES
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
