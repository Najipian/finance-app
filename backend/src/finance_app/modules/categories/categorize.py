"""Apply the rules engine to stored transactions (BR-07).

``categorize_new`` runs after each sync and only touches transactions without a
category. ``recategorize`` runs after a rule is added or removed and re-evaluates
every transaction whose category came from a rule. Manual choices are never
changed.
"""

import uuid
from collections import defaultdict

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.accounts.models import Account
from finance_app.modules.categories.engine import Rule, categorize, order_rules
from finance_app.modules.categories.repository import CategoryRepository
from finance_app.modules.connections.models import BankConnection
from finance_app.modules.transactions.models import CategorySource, Transaction

UPDATE_BATCH = 1000

log = structlog.get_logger(__name__)


class CategorizationService:
    """Categorises a user's transactions with their rules and the built-in ones.

    Args:
        session: Database session; the caller commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)

    async def categorize_new(self, user_id: uuid.UUID) -> int:
        """Categorise transactions that have no category source yet.

        Returns:
            Number of transactions that got a category.
        """
        return await self._apply(user_id, include_rule_categorized=False)

    async def recategorize(self, user_id: uuid.UUID) -> int:
        """Re-evaluate every transaction not categorised by hand.

        Returns:
            Number of transactions whose category changed.
        """
        return await self._apply(user_id, include_rule_categorized=True)

    async def _ordered_rules(self, user_id: uuid.UUID) -> list[Rule]:
        rows = await self._categories.rules_for(user_id)
        return order_rules(
            Rule(
                id=r.id,
                match_field=r.match_field,
                operator=r.operator,
                value=r.value,
                category_id=r.category_id,
                is_user_rule=r.user_id is not None,
                priority=r.priority,
                created_at=r.created_at,
            )
            for r in rows
        )

    async def _apply(self, user_id: uuid.UUID, *, include_rule_categorized: bool) -> int:
        rules = await self._ordered_rules(user_id)
        source_filter = (
            Transaction.category_source.is_distinct_from(CategorySource.MANUAL)
            if include_rule_categorized
            else Transaction.category_source.is_(None)
        )
        result = await self._session.execute(
            select(
                Transaction.id,
                Transaction.description,
                Transaction.merchant,
                Transaction.category_id,
            )
            .join(Account, Transaction.account_id == Account.id)
            .join(BankConnection, Account.connection_id == BankConnection.id)
            .where(BankConnection.user_id == user_id, source_filter)
        )
        changes: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
        for tx_id, description, merchant, current in result.all():
            category = categorize(description, merchant, rules)
            if category != current or not include_rule_categorized:
                changes[category].append(tx_id)

        changed = 0
        for category, ids in changes.items():
            if category is None and not include_rule_categorized:
                continue  # still Uncategorized: leave the source empty for later rules
            for start in range(0, len(ids), UPDATE_BATCH):
                batch = ids[start : start + UPDATE_BATCH]
                await self._session.execute(
                    update(Transaction)
                    .where(Transaction.id.in_(batch))
                    .values(
                        category_id=category,
                        category_source=CategorySource.RULE if category else None,
                    )
                )
                changed += len(batch)
        log.info("transactions_categorized", user_id=str(user_id), changed=changed)
        return changed
