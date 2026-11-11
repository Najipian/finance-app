"""Listing and filtering a user's transactions (BR-06)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.transactions.repository import TransactionFilter, TransactionRepository
from finance_app.modules.transactions.schemas import TransactionPage, TransactionRead


class TransactionService:
    """Read models for transactions.

    Args:
        session: Database session for this request.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._transactions = TransactionRepository(session)

    async def list(
        self, user_id: uuid.UUID, filters: TransactionFilter, *, limit: int, offset: int
    ) -> TransactionPage:
        """A page of the user's transactions matching ``filters`` (scoped to the user)."""
        items, total = await self._transactions.list_for_user(
            user_id, filters, limit=limit, offset=offset
        )
        return TransactionPage(
            items=[TransactionRead.model_validate(t) for t in items],
            total=total,
            limit=limit,
            offset=offset,
        )
