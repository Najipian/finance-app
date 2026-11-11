"""Queueing background jobs (arq on Redis) behind a small interface.

Services depend on ``JobQueue``, not on arq, so tests can substitute a fake and the
queue technology stays swappable.

Job IDs follow the design: ``sync:<connection_id>:<window>``. arq refuses a job
whose ID already exists, so duplicate triggers within one window collapse into a
single sync.
"""

import time
import uuid
from typing import Protocol

from arq.connections import ArqRedis

SYNC_CONNECTION_JOB = "sync_connection"
REVOKE_CONSENT_JOB = "revoke_consent"

MANUAL_SYNC_WINDOW_SECONDS = 60  # after consent or on user request
SCHEDULED_SYNC_WINDOW_SECONDS = 6 * 60 * 60  # every 6 hours (design)


def sync_job_id(connection_id: uuid.UUID, window_seconds: int, now: float | None = None) -> str:
    """The deduplicating job ID for a sync in the current time window."""
    window = int((now if now is not None else time.time()) // window_seconds)
    return f"sync:{connection_id}:{window_seconds}:{window}"


class JobQueue(Protocol):
    """Background work the API can request."""

    async def enqueue_sync(
        self, connection_id: uuid.UUID, *, window_seconds: int = MANUAL_SYNC_WINDOW_SECONDS
    ) -> bool:
        """Queue a sync; returns False if one is already queued in this window."""
        ...

    async def enqueue_revoke(self, provider: str, consent_id: str) -> None:
        """Revoke a consent at the provider in the background (retried)."""
        ...


class ArqJobQueue:
    """``JobQueue`` backed by an arq Redis pool.

    Args:
        pool: The arq pool created at startup.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_sync(
        self, connection_id: uuid.UUID, *, window_seconds: int = MANUAL_SYNC_WINDOW_SECONDS
    ) -> bool:
        """Queue ``sync_connection`` unless one is already queued in this window."""
        job = await self._pool.enqueue_job(
            SYNC_CONNECTION_JOB,
            str(connection_id),
            _job_id=sync_job_id(connection_id, window_seconds),
        )
        return job is not None

    async def enqueue_revoke(self, provider: str, consent_id: str) -> None:
        """Queue ``revoke_consent`` (one job per consent)."""
        await self._pool.enqueue_job(
            REVOKE_CONSENT_JOB, provider, consent_id, _job_id=f"revoke:{consent_id}"
        )
