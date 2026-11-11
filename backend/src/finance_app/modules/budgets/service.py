"""Monthly budgets, spend tracking and threshold alerts (BR-09, BR-10).

Spend for a budget is the *net* outflow of the category in that month and currency:
debits count, refunds reduce it, and pending transactions are included so users see
spending immediately. Each threshold (80 %, 100 %) alerts once per budget; raising a
limit so spend falls back below a threshold re-arms that alert.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.errors import NotFoundError
from finance_app.modules.accounts.models import Account
from finance_app.modules.budgets.models import Budget
from finance_app.modules.categories.models import Category
from finance_app.modules.categories.repository import CategoryRepository
from finance_app.modules.connections.models import BankConnection
from finance_app.modules.notifications.service import NotificationService
from finance_app.modules.transactions.models import Transaction

WARNING_RATIO = Decimal("0.80")
CENT = Decimal("0.01")

log = structlog.get_logger(__name__)


def month_start(day: date) -> date:
    """First day of the month containing ``day``."""
    return day.replace(day=1)


def next_month(month: date) -> date:
    """First day of the following month."""
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def thresholds_reached(spent: Decimal, limit: Decimal) -> tuple[bool, bool]:
    """Whether spend has reached 80 % and 100 % of the limit."""
    if limit <= 0:
        return spent > 0, spent > 0
    return spent >= limit * WARNING_RATIO, spent >= limit


@dataclass(frozen=True, slots=True)
class BudgetView:
    """A budget with its category name and spend so far."""

    budget: Budget
    category_name: str
    spent: Decimal


class BudgetService:
    """Budget use cases.

    Args:
        session: Database session for this request or job.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)
        self._notifications = NotificationService(session)

    async def spend_by_category(
        self, user_id: uuid.UUID, month: date
    ) -> dict[tuple[uuid.UUID, str], Decimal]:
        """Net outflow per (category, currency) for the user in a month."""
        result = await self._session.execute(
            select(Transaction.category_id, Transaction.currency, func.sum(Transaction.amount))
            .join(Account, Transaction.account_id == Account.id)
            .join(BankConnection, Account.connection_id == BankConnection.id)
            .where(
                BankConnection.user_id == user_id,
                Transaction.category_id.is_not(None),
                Transaction.booking_date >= month,
                Transaction.booking_date < next_month(month),
            )
            .group_by(Transaction.category_id, Transaction.currency)
        )
        return {
            (category_id, currency): max(Decimal(0), -total)
            for category_id, currency, total in result.all()
            if category_id is not None  # filtered in SQL; this narrows the type
        }

    async def list(self, user_id: uuid.UUID, month: date) -> list[BudgetView]:
        """The user's budgets for a month with spend so far."""
        result = await self._session.execute(
            select(Budget, Category.name)
            .join(Category, Budget.category_id == Category.id)
            .where(Budget.user_id == user_id, Budget.month == month_start(month))
            .order_by(Category.name)
        )
        spend = await self.spend_by_category(user_id, month_start(month))
        return [
            BudgetView(b, name, spend.get((b.category_id, b.currency), Decimal(0)))
            for b, name in result.all()
        ]

    async def set_budget(
        self,
        user_id: uuid.UUID,
        category_id: uuid.UUID,
        month: date,
        limit_amount: Decimal,
        currency: str,
    ) -> BudgetView:
        """Create or update a budget, then check its alerts.

        Raises:
            NotFoundError: The category isn't available to the user.
        """
        category = await self._categories.get_visible(user_id, category_id)
        if category is None:
            raise NotFoundError("Category not found.")
        month = month_start(month)
        limit_amount = limit_amount.quantize(CENT)
        statement = insert(Budget).values(
            id=uuid.uuid4(),
            user_id=user_id,
            category_id=category_id,
            month=month,
            limit_amount=limit_amount,
            currency=currency,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[Budget.user_id, Budget.category_id, Budget.month],
                set_={"limit_amount": limit_amount, "currency": currency, "updated_at": func.now()},
            )
        )
        budget = (
            await self._session.execute(
                select(Budget).where(
                    Budget.user_id == user_id,
                    Budget.category_id == category_id,
                    Budget.month == month,
                )
            )
        ).scalar_one()
        await self._session.refresh(budget)
        spent = (await self.spend_by_category(user_id, month)).get(
            (category_id, currency), Decimal(0)
        )
        # Re-arm alerts if the new limit puts spend back under a threshold.
        reached_80, reached_100 = thresholds_reached(spent, limit_amount)
        budget.alerted_80 = budget.alerted_80 and reached_80
        budget.alerted_100 = budget.alerted_100 and reached_100
        self._alert_if_needed(budget, category.name, spent)
        await self._session.commit()
        return BudgetView(budget, category.name, spent)

    async def delete(self, user_id: uuid.UUID, budget_id: uuid.UUID) -> None:
        """Delete one of the user's budgets.

        Raises:
            NotFoundError: Not found for this user.
        """
        budget = (
            await self._session.execute(
                select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id)
            )
        ).scalar_one_or_none()
        if budget is None:
            raise NotFoundError("Budget not found.")
        await self._session.delete(budget)
        await self._session.commit()

    async def check_alerts(self, user_id: uuid.UUID, month: date) -> int:
        """Send any 80 % / 100 % alerts now due for the month (each once).

        Returns:
            Number of alerts created. The caller commits.
        """
        views = await self.list(user_id, month)
        return sum(self._alert_if_needed(v.budget, v.category_name, v.spent) for v in views)

    def _alert_if_needed(self, budget: Budget, category_name: str, spent: Decimal) -> int:
        reached_80, reached_100 = thresholds_reached(spent, budget.limit_amount)
        label = f"{category_name} ({budget.month:%B %Y})"
        amounts = f"{spent:.2f} of {budget.limit_amount:.2f} {budget.currency}"
        if reached_100 and not budget.alerted_100:
            budget.alerted_100 = budget.alerted_80 = True
            self._notifications.notify(
                budget.user_id,
                "budget_exceeded",
                f"Budget reached: {category_name}",
                f"You've spent {amounts} of your {label} budget.",
            )
            log.info("budget_alert", budget_id=str(budget.id), threshold=100)
            return 1
        if reached_80 and not budget.alerted_80:
            budget.alerted_80 = True
            self._notifications.notify(
                budget.user_id,
                "budget_warning",
                f"80% of budget used: {category_name}",
                f"You've spent {amounts} of your {label} budget.",
            )
            log.info("budget_alert", budget_id=str(budget.id), threshold=80)
            return 1
        return 0


def percent_used(spent: Decimal, limit: Decimal) -> Decimal:
    """Spend as a percentage of the limit, one decimal place."""
    if limit <= 0:
        return Decimal("0.0")
    return (spent / limit * 100).quantize(Decimal("0.1"))


def budget_status(spent: Decimal, limit: Decimal) -> str:
    """``ok``, ``warning`` (≥ 80 %) or ``exceeded`` (≥ 100 %)."""
    reached_80, reached_100 = thresholds_reached(spent, limit)
    return "exceeded" if reached_100 else "warning" if reached_80 else "ok"
