"""Database access for bank connections. Every user-facing query is scoped by user."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.connections.models import BankConnection, ConnectionStatus


class ConnectionRepository:
    """Queries for the ``bank_connections`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, connection: BankConnection) -> None:
        """Stage a new connection for insert."""
        self._session.add(connection)

    async def get(self, connection_id: uuid.UUID) -> BankConnection | None:
        """Load a connection by ID (internal use, e.g. background jobs)."""
        return await self._session.get(BankConnection, connection_id)

    async def get_for_user(
        self, connection_id: uuid.UUID, user_id: uuid.UUID
    ) -> BankConnection | None:
        """Load a connection only if it belongs to ``user_id``."""
        result = await self._session.execute(
            select(BankConnection).where(
                BankConnection.id == connection_id, BankConnection.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[BankConnection]:
        """A user's connections, newest first, excluding abandoned pending ones."""
        result = await self._session.execute(
            select(BankConnection)
            .where(
                BankConnection.user_id == user_id,
                BankConnection.status != ConnectionStatus.PENDING,
            )
            .order_by(BankConnection.created_at.desc())
        )
        return result.scalars().all()

    async def delete(self, connection: BankConnection) -> None:
        """Delete a connection (accounts and balances cascade)."""
        await self._session.delete(connection)
