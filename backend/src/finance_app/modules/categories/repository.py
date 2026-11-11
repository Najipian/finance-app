"""Database access for categories and rules. User-facing queries are user-scoped."""

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.categories.models import Category, CategoryRule


class CategoryRepository:
    """Queries for ``categories`` and ``category_rules``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def visible_to(self, user_id: uuid.UUID) -> Sequence[Category]:
        """Built-in categories plus the user's own, by name."""
        result = await self._session.execute(
            select(Category)
            .where(or_(Category.user_id.is_(None), Category.user_id == user_id))
            .order_by(Category.name)
        )
        return result.scalars().all()

    async def get_visible(self, user_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
        """A category the user may use (built-in or their own), else None."""
        result = await self._session.execute(
            select(Category).where(
                Category.id == category_id,
                or_(Category.user_id.is_(None), Category.user_id == user_id),
            )
        )
        return result.scalar_one_or_none()

    async def name_taken(self, user_id: uuid.UUID, name: str) -> bool:
        """Whether a built-in or user category already has this name (case-insensitive)."""
        result = await self._session.execute(
            select(Category.id).where(
                or_(Category.user_id.is_(None), Category.user_id == user_id),
                Category.name.ilike(name),
            )
        )
        return result.first() is not None

    def add(self, item: Category | CategoryRule) -> None:
        """Stage a new category or rule."""
        self._session.add(item)

    async def delete(self, item: Category | CategoryRule) -> None:
        """Delete a category (rules cascade, transactions become Uncategorized) or rule."""
        await self._session.delete(item)

    async def rules_for(self, user_id: uuid.UUID) -> Sequence[CategoryRule]:
        """Built-in rules plus the user's own (unordered; the engine orders them)."""
        result = await self._session.execute(
            select(CategoryRule).where(
                or_(CategoryRule.user_id.is_(None), CategoryRule.user_id == user_id)
            )
        )
        return result.scalars().all()

    async def user_rules(self, user_id: uuid.UUID) -> Sequence[CategoryRule]:
        """Only the user's own rules, newest first."""
        result = await self._session.execute(
            select(CategoryRule)
            .where(CategoryRule.user_id == user_id)
            .order_by(CategoryRule.priority, CategoryRule.created_at.desc())
        )
        return result.scalars().all()

    async def get_user_rule(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> CategoryRule | None:
        """One of the user's own rules, else None."""
        result = await self._session.execute(
            select(CategoryRule).where(CategoryRule.id == rule_id, CategoryRule.user_id == user_id)
        )
        return result.scalar_one_or_none()
