"""Synchronise a connection: accounts, balances and transactions (BR-05, BR-06).

Runs in the background worker, never in an HTTP request.

- Window: the first sync fetches ``INITIAL_HISTORY_DAYS``; later syncs fetch from
  ``last_synced_at`` minus ``OVERLAP_DAYS`` to catch late-posted transactions.
- Writes are upserts keyed by provider IDs and dedup keys, so re-running a sync
  never duplicates data. Pending transactions the bank no longer reports in the
  window are removed (they booked under a new ID or were dropped).
- One commit at the end: a provider failure halfway leaves the previous state.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.crypto import TokenCipher
from finance_app.modules.accounts.repository import AccountRepository
from finance_app.modules.connections.models import (
    BankConnection,
    ConnectionStatus,
    SyncStatus,
)
from finance_app.modules.connections.repository import ConnectionRepository
from finance_app.modules.transactions.dedup import dedup_keys
from finance_app.modules.transactions.repository import TransactionRepository
from finance_app.providers.base import BankProvider, ProviderAuthError

INITIAL_HISTORY_DAYS = 365
OVERLAP_DAYS = 3

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SyncResult:
    """What one sync changed, and whose data it was."""

    user_id: uuid.UUID
    accounts: int
    transactions: int
    stale_pending_removed: int


class ConnectionSyncService:
    """Pulls one connection's data from the provider into the database.

    Args:
        session: Database session owned by the job.
        provider: The configured Open Banking provider.
        cipher: Decrypts the stored consent token.
    """

    def __init__(self, session: AsyncSession, provider: BankProvider, cipher: TokenCipher) -> None:
        self._session = session
        self._provider = provider
        self._cipher = cipher
        self._connections = ConnectionRepository(session)
        self._accounts = AccountRepository(session)
        self._transactions = TransactionRepository(session)

    async def sync(self, connection_id: uuid.UUID) -> SyncResult | None:
        """Sync accounts, balances and transactions for one connection.

        Args:
            connection_id: The connection to sync.

        Returns:
            What changed, or None if the connection is gone, not active, or its
            consent has expired (it is then marked ``needs_renewal``).

        Raises:
            ProviderError: Transient provider failure; nothing is written and the
                caller may retry.
        """
        connection = await self._connections.get(connection_id)
        if connection is None or connection.status is not ConnectionStatus.ACTIVE:
            log.info("sync_skipped", connection_id=str(connection_id))
            return None
        if connection.consent_token_enc is None:
            log.warning("sync_skipped_no_token", connection_id=str(connection_id))
            return None

        now = datetime.now(UTC)
        date_to = now.date()
        date_from = (
            (connection.last_synced_at - timedelta(days=OVERLAP_DAYS)).date()
            if connection.last_synced_at
            else date_to - timedelta(days=INITIAL_HISTORY_DAYS)
        )
        token = self._cipher.decrypt(
            connection.consent_token_enc, associated_data=connection.id.bytes
        )
        try:
            result = await self._pull(connection, token, date_from, date_to)
        except ProviderAuthError:
            await self._session.rollback()
            await self._mark_consent_expired(connection)
            return None
        except Exception:
            await self._session.rollback()
            raise

        connection.last_synced_at = now
        connection.last_sync_attempt_at = now
        connection.last_sync_status = SyncStatus.OK
        connection.last_sync_error = None
        await self._session.commit()
        log.info(
            "connection_synced",
            connection_id=str(connection_id),
            accounts=result.accounts,
            transactions=result.transactions,
            stale_pending_removed=result.stale_pending_removed,
        )
        return result

    async def _pull(
        self, connection: BankConnection, token: str, date_from: date, date_to: date
    ) -> SyncResult:
        accounts = await self._provider.get_accounts(token)
        transactions = removed = 0
        for account in accounts:
            account_id = await self._accounts.upsert_account(connection.id, account)
            balances = await self._provider.get_balances(token, account.provider_account_id)
            await self._accounts.upsert_balances(account_id, balances)
            txs = await self._provider.get_transactions(
                token, account.provider_account_id, date_from, date_to
            )
            keys = dedup_keys(account_id, txs)
            await self._transactions.upsert_many(account_id, txs, keys)
            await self._transactions.carry_manual_categories(account_id, date_from, keys)
            removed += await self._transactions.delete_stale_pending(
                account_id,
                date_from,
                keys,
            )
            transactions += len(txs)
        return SyncResult(
            user_id=connection.user_id,
            accounts=len(accounts),
            transactions=transactions,
            stale_pending_removed=removed,
        )

    async def _mark_consent_expired(self, connection: BankConnection) -> None:
        connection.status = ConnectionStatus.NEEDS_RENEWAL
        connection.last_sync_status = SyncStatus.FAILED
        connection.last_sync_error = "consent_expired"
        connection.last_sync_attempt_at = datetime.now(UTC)
        await self._session.commit()
        log.warning("consent_needs_renewal", connection_id=str(connection.id))

    async def record_failure(self, connection_id: uuid.UUID, *, final: bool) -> None:
        """Make a failed attempt visible: ``retrying`` or, after the last try, ``failed``."""
        connection = await self._connections.get(connection_id)
        if connection is None:
            return
        connection.last_sync_status = SyncStatus.FAILED if final else SyncStatus.RETRYING
        connection.last_sync_error = "provider_unavailable"
        connection.last_sync_attempt_at = datetime.now(UTC)
        await self._session.commit()
