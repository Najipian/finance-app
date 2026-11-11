"""Database access for refresh tokens."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.auth.models import RefreshToken


class RefreshTokenRepository:
    """Queries for the ``refresh_tokens`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: RefreshToken) -> None:
        """Stage a new refresh token for insert."""
        self._session.add(token)

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """Load a token by hash and lock its row until the transaction ends.

        The lock stops two concurrent refreshes of the same token from both
        succeeding and forking the family.
        """
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )
        return result.scalar_one_or_none()

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        """Revoke every still-active token in a family."""
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
