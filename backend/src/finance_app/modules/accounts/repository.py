"""Database access for accounts and balances."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

from finance_app.modules.accounts.models import Account, Balance
from finance_app.modules.connections.models import BankConnection, ConnectionStatus
from finance_app.providers.base import ProviderAccount, ProviderBalance

CENT = Decimal("0.01")


class AccountRepository:
    """Queries for ``accounts`` and ``balances``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_account(self, connection_id: uuid.UUID, account: ProviderAccount) -> uuid.UUID:
        """Insert or update an account by (connection, provider account ID).

        Returns:
            The account's ID.
        """
        values = {
            "name": account.name,
            "type": account.type,
            "currency": account.currency,
            "account_number_masked": account.account_number_masked,
            "updated_at": datetime.now(UTC),
        }
        statement = (
            insert(Account)
            .values(
                id=uuid.uuid4(),
                connection_id=connection_id,
                provider_account_id=account.provider_account_id,
                **values,
            )
            .on_conflict_do_update(
                index_elements=[Account.connection_id, Account.provider_account_id], set_=values
            )
            .returning(Account.id)
        )
        return (await self._session.execute(statement)).scalar_one()

    async def upsert_balances(
        self, account_id: uuid.UUID, balances: Sequence[ProviderBalance]
    ) -> None:
        """Store the latest value of each balance type (rounded to the cent)."""
        for balance in balances:
            values = {
                "amount": balance.amount.quantize(CENT),
                "currency": balance.currency,
                "as_of": balance.as_of,
            }
            await self._session.execute(
                insert(Balance)
                .values(id=uuid.uuid4(), account_id=account_id, type=balance.type, **values)
                .on_conflict_do_update(
                    index_elements=[Balance.account_id, Balance.type], set_=values
                )
            )

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Account]:
        """All accounts the user can see, with balances and their connection loaded."""
        result = await self._session.execute(
            select(Account)
            .join(BankConnection, Account.connection_id == BankConnection.id)
            .where(
                BankConnection.user_id == user_id,
                BankConnection.status.in_(
                    [ConnectionStatus.ACTIVE, ConnectionStatus.NEEDS_RENEWAL]
                ),
            )
            .options(contains_eager(Account.connection), selectinload(Account.balances))
            .order_by(BankConnection.institution_name, Account.name)
        )
        return result.scalars().unique().all()
