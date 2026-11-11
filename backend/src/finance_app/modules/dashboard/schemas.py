"""API schemas for the dashboard (BR-11). Amounts are decimal strings."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class CategorySpend(BaseModel):
    """Net spending in one category this month."""

    category_id: uuid.UUID | None = Field(description="None = Uncategorized.")
    name: str = Field(examples=["Eating out"])
    amount: Decimal = Field(examples=["139.40"])
    share_percent: Decimal = Field(examples=["24.5"], description="Share of the month's spending.")


class MonthTotals(BaseModel):
    """Spending and income for one month."""

    month: str = Field(examples=["2026-11"])
    spending: Decimal = Field(examples=["1520.33"])
    income: Decimal = Field(examples=["2850.00"])


class CurrencySummary(BaseModel):
    """Everything for one currency (currencies are never mixed)."""

    currency: str = Field(examples=["GBP"])
    spending: Decimal
    income: Decimal
    by_category: list[CategorySpend] = Field(description="Largest first.")
    trend: list[MonthTotals] = Field(
        description="The six months ending with `month`, oldest first."
    )


class DashboardSummary(BaseModel):
    """Dashboard data for a month."""

    month: str = Field(examples=["2026-11"])
    currencies: list[CurrencySummary]
