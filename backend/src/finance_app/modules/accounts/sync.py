"""Pull accounts and balances from the provider into the database.

Runs in the background worker, never in an HTTP request. Writes are upserts keyed
by provider IDs, so running it twice never duplicates rows.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.crypto import TokenCipher
from finance_app.modules.accounts.repository import AccountRepository
from finance_app.modules.connections.models import ConnectionStatus
from finance_app.modules.connections.repository import ConnectionRepository
from finance_app.providers.base import BankProvider, ProviderAuthError

log = structlog.get_logger(__name__)


class AccountSyncService:
    """Synchronises one connection's accounts and balances.

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

    async def sync_connection(self, connection_id: uuid.UUID) -> int:
        """Fetch and store the connection's accounts and balances.

        Args:
            connection_id: The connection to sync.

        Returns:
            Number of accounts synced (0 if skipped or consent needs renewal).

        Raises:
            ProviderError: Transient provider failure (the job may be retried).
        """
        connection = await self._connections.get(connection_id)
        if (
            connection is None
            or connection.status is not ConnectionStatus.ACTIVE
            or connection.consent_token_enc is None
        ):
            log.info("sync_skipped", connection_id=str(connection_id))
            return 0
        token = self._cipher.decrypt(
            connection.consent_token_enc, associated_data=connection.id.bytes
        )
        try:
            accounts = await self._provider.get_accounts(token)
            for account in accounts:
                account_id = await self._accounts.upsert_account(connection.id, account)
                balances = await self._provider.get_balances(token, account.provider_account_id)
                await self._accounts.upsert_balances(account_id, balances)
        except ProviderAuthError:
            await self._session.rollback()
            connection.status = ConnectionStatus.NEEDS_RENEWAL
            await self._session.commit()
            log.warning("consent_needs_renewal", connection_id=str(connection_id))
            return 0
        connection.last_synced_at = datetime.now(UTC)
        await self._session.commit()
        log.info("accounts_synced", connection_id=str(connection_id), accounts=len(accounts))
        return len(accounts)
