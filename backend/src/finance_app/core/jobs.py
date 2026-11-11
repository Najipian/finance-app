"""Queueing background jobs (arq on Redis) behind a small interface.

Services depend on ``JobQueue``, not on arq, so tests can substitute a fake and
the queue technology stays swappable.
"""

import time
import uuid
from typing import Protocol

from arq.connections import ArqRedis

SYNC_ACCOUNTS_JOB = "sync_accounts"
# Duplicate triggers within this window collapse into one job (arq job IDs are unique).
DEDUP_WINDOW_SECONDS = 60


class JobQueue(Protocol):
    """Background work the API can request."""

    async def enqueue_account_sync(self, connection_id: uuid.UUID) -> None:
        """Fetch a connection's accounts and balances from the provider."""
        ...


class ArqJobQueue:
    """``JobQueue`` backed by an arq Redis pool.

    Args:
        pool: The arq pool created at startup.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_account_sync(self, connection_id: uuid.UUID) -> None:
        """Queue ``sync_accounts``; repeats within a minute are ignored."""
        window = int(time.time() // DEDUP_WINDOW_SECONDS)
        await self._pool.enqueue_job(
            SYNC_ACCOUNTS_JOB,
            str(connection_id),
            _job_id=f"{SYNC_ACCOUNTS_JOB}:{connection_id}:{window}",
        )
