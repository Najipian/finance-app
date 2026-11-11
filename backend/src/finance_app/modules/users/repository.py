"""Database access for users."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.users.models import User


class UserRepository:
    """Queries for the ``users`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the user with this ID, or None."""
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this (already lower-cased) email, or None."""
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    def add(self, user: User) -> None:
        """Stage a new user for insert on the next flush/commit."""
        self._session.add(user)
