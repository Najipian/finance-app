"""Category and rule management, and manual re-categorisation (BR-07, BR-08)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.errors import ConflictError, NotFoundError
from finance_app.modules.budgets.service import BudgetService
from finance_app.modules.categories.categorize import CategorizationService
from finance_app.modules.categories.models import (
    Category,
    CategoryRule,
    RuleField,
    RuleOperator,
)
from finance_app.modules.categories.repository import CategoryRepository
from finance_app.modules.transactions.models import CategorySource, Transaction
from finance_app.modules.transactions.repository import TransactionRepository

log = structlog.get_logger(__name__)


class CategoryService:
    """Use cases for categories, rules and changing a transaction's category.

    Args:
        session: Database session for this request.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)
        self._transactions = TransactionRepository(session)
        self._categorizer = CategorizationService(session)
        self._budgets = BudgetService(session)

    # ------------------------------------------------------------------ categories

    async def list_categories(self, user_id: uuid.UUID) -> Sequence[Category]:
        """Built-in plus the user's own categories."""
        return await self._categories.visible_to(user_id)

    async def create_category(self, user_id: uuid.UUID, name: str, icon: str | None) -> Category:
        """Create a user category.

        Raises:
            ConflictError: A built-in or user category already has this name.
        """
        name = name.strip()
        if await self._categories.name_taken(user_id, name):
            raise ConflictError("A category with this name already exists.")
        category = Category(user_id=user_id, name=name, icon=icon)
        self._categories.add(category)
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def delete_category(self, user_id: uuid.UUID, category_id: uuid.UUID) -> None:
        """Delete a user category; its rules go too, its transactions become Uncategorized.

        Raises:
            NotFoundError: Not one of the user's categories.
            ConflictError: Built-in categories can't be deleted.
        """
        category = await self._categories.get_visible(user_id, category_id)
        if category is None:
            raise NotFoundError("Category not found.")
        if category.user_id is None:
            raise ConflictError("Built-in categories can't be deleted.")
        await self._categories.delete(category)
        await self._session.flush()
        await self._categorizer.recategorize(user_id)
        await self._session.commit()

    # ------------------------------------------------------------------ rules

    async def list_rules(self, user_id: uuid.UUID) -> Sequence[CategoryRule]:
        """The user's own rules."""
        return await self._categories.user_rules(user_id)

    async def create_rule(
        self,
        user_id: uuid.UUID,
        match_field: RuleField,
        operator: RuleOperator,
        value: str,
        category_id: uuid.UUID,
        priority: int = 100,
    ) -> tuple[CategoryRule, int]:
        """Create a rule and apply it to existing transactions.

        Returns:
            The rule and how many transactions changed category.

        Raises:
            NotFoundError: The category isn't available to the user.
        """
        if await self._categories.get_visible(user_id, category_id) is None:
            raise NotFoundError("Category not found.")
        rule = CategoryRule(
            user_id=user_id,
            match_field=match_field,
            operator=operator,
            value=value.strip(),
            category_id=category_id,
            priority=priority,
            created_at=datetime.now(UTC),
        )
        self._categories.add(rule)
        await self._session.flush()
        changed = await self._categorizer.recategorize(user_id)
        await self._budgets.check_alerts(user_id, datetime.now(UTC).date())
        await self._session.commit()
        log.info("rule_created", user_id=str(user_id), rule_id=str(rule.id), changed=changed)
        return rule, changed

    async def delete_rule(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> None:
        """Delete one of the user's rules and re-evaluate their transactions.

        Raises:
            NotFoundError: Not one of the user's rules.
        """
        rule = await self._categories.get_user_rule(user_id, rule_id)
        if rule is None:
            raise NotFoundError("Rule not found.")
        await self._categories.delete(rule)
        await self._session.flush()
        await self._categorizer.recategorize(user_id)
        await self._session.commit()

    # ------------------------------------------------------------------ transactions

    async def recategorize_transaction(
        self,
        user_id: uuid.UUID,
        transaction_id: uuid.UUID,
        category_id: uuid.UUID | None,
        *,
        apply_to_similar: bool,
    ) -> tuple[Transaction, uuid.UUID | None, int]:
        """Set a transaction's category by hand (BR-08).

        With ``apply_to_similar``, also create an exact-match rule (merchant if the bank
        gave one, otherwise description) and apply it to the user's other transactions.

        Returns:
            The transaction, the new rule's ID (if any) and how many others changed.

        Raises:
            NotFoundError: The transaction or category isn't the user's.
        """
        transaction = await self._transactions.get_for_user(transaction_id, user_id)
        if transaction is None:
            raise NotFoundError("Transaction not found.")
        if category_id and await self._categories.get_visible(user_id, category_id) is None:
            raise NotFoundError("Category not found.")

        transaction.category_id = category_id
        transaction.category_source = CategorySource.MANUAL
        rule_id: uuid.UUID | None = None
        changed = 0
        if apply_to_similar and category_id:
            field = RuleField.MERCHANT if transaction.merchant else RuleField.DESCRIPTION
            rule = CategoryRule(
                user_id=user_id,
                match_field=field,
                operator=RuleOperator.EQUALS,
                value=(transaction.merchant or transaction.description)[:100],
                category_id=category_id,
                priority=100,
                created_at=datetime.now(UTC),
            )
            self._categories.add(rule)
            await self._session.flush()
            rule_id = rule.id
            changed = await self._categorizer.recategorize(user_id)
        else:
            await self._session.flush()
        await self._budgets.check_alerts(user_id, transaction.booking_date)
        await self._session.commit()
        await self._session.refresh(transaction)
        return transaction, rule_id, changed
