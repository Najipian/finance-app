"""Database access for transactions."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from finance_app.modules.accounts.models import Account
from finance_app.modules.connections.models import BankConnection
from finance_app.modules.transactions.models import (
    CategorySource,
    Transaction,
    TransactionStatus,
)
from finance_app.providers.base import ProviderTransaction

CENT = Decimal("0.01")
CARRY_OVER_DAYS = 7  # how long a pending transaction may take to book
UPSERT_BATCH = 500
_UPDATABLE = (
    "provider_transaction_id",
    "booking_date",
    "amount",
    "currency",
    "description",
    "merchant",
    "status",
    "updated_at",
)


@dataclass(frozen=True, slots=True)
class TransactionFilter:
    """Filters for listing a user's transactions."""

    account_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: TransactionStatus | None = None
    text: str | None = None


class TransactionRepository:
    """Queries for the ``transactions`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(
        self,
        account_id: uuid.UUID,
        transactions: Sequence[ProviderTransaction],
        keys: Sequence[str],
    ) -> None:
        """Insert new transactions and update known ones (matched by dedup key).

        A pending transaction that books under the same key is updated in place.
        """
        now = datetime.now(UTC)
        rows = [
            {
                "id": uuid.uuid4(),
                "account_id": account_id,
                "dedup_key": key,
                "provider_transaction_id": tx.provider_transaction_id,
                "booking_date": tx.booking_date,
                "amount": tx.amount.quantize(CENT),
                "currency": tx.currency,
                "description": tx.description,
                "merchant": tx.merchant,
                "status": TransactionStatus(tx.status),
                "updated_at": now,
            }
            for tx, key in zip(transactions, keys, strict=True)
        ]
        for start in range(0, len(rows), UPSERT_BATCH):
            statement = insert(Transaction).values(rows[start : start + UPSERT_BATCH])
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Transaction.account_id, Transaction.dedup_key],
                    set_={column: statement.excluded[column] for column in _UPDATABLE},
                )
            )

    async def carry_manual_categories(
        self, account_id: uuid.UUID, date_from: date, keep_keys: Sequence[str]
    ) -> int:
        """Copy hand-set categories from stale pending rows to their booked versions.

        Runs before ``delete_stale_pending``: when a pending transaction books under a
        new ID, the user's manual category would otherwise be lost (ADR 0004). The
        booked row must be on the same account with the same amount and description,
        booked within ``CARRY_OVER_DAYS``, and not already set by hand.

        Returns:
            Number of booked rows that received a category.
        """
        pending = aliased(Transaction)
        conditions = [
            pending.account_id == account_id,
            pending.status == TransactionStatus.PENDING,
            pending.booking_date >= date_from,
            pending.category_source == CategorySource.MANUAL,
            Transaction.account_id == pending.account_id,
            Transaction.status == TransactionStatus.BOOKED,
            Transaction.amount == pending.amount,
            Transaction.description == pending.description,
            Transaction.booking_date >= pending.booking_date,
            Transaction.booking_date <= pending.booking_date + CARRY_OVER_DAYS,
            Transaction.category_source.is_distinct_from(CategorySource.MANUAL),
        ]
        if keep_keys:
            conditions.append(pending.dedup_key.not_in(keep_keys))
        result = await self._session.execute(
            update(Transaction)
            .where(*conditions)
            .values(category_id=pending.category_id, category_source=CategorySource.MANUAL)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def delete_stale_pending(
        self, account_id: uuid.UUID, date_from: date, keep_keys: Sequence[str]
    ) -> int:
        """Delete pending transactions in the window that the bank no longer reports.

        A pending transaction often books under a *new* provider ID; the old pending
        row would otherwise remain as a duplicate.

        Returns:
            Number of rows deleted.
        """
        statement = delete(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.status == TransactionStatus.PENDING,
            Transaction.booking_date >= date_from,
        )
        if keep_keys:
            statement = statement.where(Transaction.dedup_key.not_in(keep_keys))
        result = await self._session.execute(statement)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def get_for_user(
        self, transaction_id: uuid.UUID, user_id: uuid.UUID
    ) -> Transaction | None:
        """A transaction only if it belongs to the user."""
        result = await self._session.execute(
            select(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .join(BankConnection, Account.connection_id == BankConnection.id)
            .where(Transaction.id == transaction_id, BankConnection.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, filters: TransactionFilter, *, limit: int, offset: int
    ) -> tuple[Sequence[Transaction], int]:
        """A page of the user's transactions, newest first, and the total count."""
        query = (
            select(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .join(BankConnection, Account.connection_id == BankConnection.id)
            .where(BankConnection.user_id == user_id)
        )
        if filters.account_id:
            query = query.where(Transaction.account_id == filters.account_id)
        if filters.date_from:
            query = query.where(Transaction.booking_date >= filters.date_from)
        if filters.date_to:
            query = query.where(Transaction.booking_date <= filters.date_to)
        if filters.status:
            query = query.where(Transaction.status == filters.status)
        if filters.text:
            pattern = f"%{filters.text}%"  # bound parameter: no SQL injection
            query = query.where(
                Transaction.description.ilike(pattern) | Transaction.merchant.ilike(pattern)
            )
        total = (
            await self._session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        page = await self._session.execute(
            query.order_by(Transaction.booking_date.desc(), Transaction.id)
            .limit(limit)
            .offset(offset)
        )
        return page.scalars().all(), int(total)
