"""Dashboard summary: spending by category and a 6-month trend (BR-11, NFR-08).

One grouped query over six months (month by category by currency) feeds both the
category breakdown and the trend, so the dashboard stays fast with a year of data.

Definitions, consistent with budgets:

- Spending per category is the *net* outflow (refunds reduce it).
- The built-in *Income* category counts as income, never as spending.
- The built-in *Transfers* category is ignored: moving money between your own
  accounts is neither spending nor income.
"""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.accounts.models import Account
from finance_app.modules.budgets.service import month_start, next_month
from finance_app.modules.categories.repository import CategoryRepository
from finance_app.modules.connections.models import BankConnection
from finance_app.modules.dashboard.schemas import (
    CategorySpend,
    CurrencySummary,
    DashboardSummary,
    MonthTotals,
)
from finance_app.modules.transactions.models import Transaction

TREND_MONTHS = 6
INCOME_CATEGORY = "Income"
TRANSFER_CATEGORY = "Transfers"
UNCATEGORIZED = "Uncategorized"
ZERO = Decimal("0.00")


def months_back(month: date, count: int) -> list[date]:
    """``count`` month starts ending with ``month``, oldest first."""
    months = [month_start(month)]
    for _ in range(count - 1):
        first = months[0]
        months.insert(0, date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1))
    return months


class DashboardService:
    """Read model for the dashboard.

    Args:
        session: Database session for this request.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)

    async def summary(self, user_id: uuid.UUID, month: date) -> DashboardSummary:
        """Spending by category for ``month`` and the six-month trend, per currency."""
        months = months_back(month, TREND_MONTHS)
        categories = await self._categories.visible_to(user_id)
        names = {c.id: c.name for c in categories}
        income_ids = {c.id for c in categories if c.user_id is None and c.name == INCOME_CATEGORY}
        transfer_ids = {
            c.id for c in categories if c.user_id is None and c.name == TRANSFER_CATEGORY
        }

        month_bucket = func.date_trunc("month", Transaction.booking_date)
        rows = await self._session.execute(
            select(
                month_bucket,
                Transaction.category_id,
                Transaction.currency,
                func.sum(Transaction.amount),
            )
            .join(Account, Transaction.account_id == Account.id)
            .join(BankConnection, Account.connection_id == BankConnection.id)
            .where(
                BankConnection.user_id == user_id,
                Transaction.booking_date >= months[0],
                Transaction.booking_date < next_month(months[-1]),
            )
            .group_by(month_bucket, Transaction.category_id, Transaction.currency)
        )

        spending: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        income: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        current: dict[str, dict[uuid.UUID | None, Decimal]] = defaultdict(dict)
        for bucket, category_id, currency, total in rows.all():
            bucket_month = bucket.date() if hasattr(bucket, "date") else bucket
            if category_id in transfer_ids:
                continue
            if category_id in income_ids:
                income[currency][bucket_month] += max(ZERO, total)
                continue
            outflow = max(ZERO, -total)
            spending[currency][bucket_month] += outflow
            if bucket_month == months[-1] and outflow > 0:
                current[currency][category_id] = outflow

        result = []
        for currency in sorted(set(spending) | set(income)):
            month_spend = spending[currency][months[-1]]
            by_category = sorted(
                (
                    CategorySpend(
                        category_id=category_id,
                        name=names.get(category_id, UNCATEGORIZED)
                        if category_id
                        else UNCATEGORIZED,
                        amount=amount.quantize(ZERO),
                        share_percent=(amount / month_spend * 100).quantize(Decimal("0.1")),
                    )
                    for category_id, amount in current[currency].items()
                ),
                key=lambda c: (-c.amount, c.name),
            )
            result.append(
                CurrencySummary(
                    currency=currency,
                    spending=month_spend.quantize(ZERO),
                    income=income[currency][months[-1]].quantize(ZERO),
                    by_category=by_category,
                    trend=[
                        MonthTotals(
                            month=f"{m:%Y-%m}",
                            spending=spending[currency][m].quantize(ZERO),
                            income=income[currency][m].quantize(ZERO),
                        )
                        for m in months
                    ],
                )
            )
        return DashboardSummary(month=f"{months[-1]:%Y-%m}", currencies=result)
