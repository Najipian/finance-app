"""API schemas for budgets (BR-09) and notifications (BR-10)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def parse_month(value: str) -> date:
    """``"2026-11"`` → ``date(2026, 11, 1)`` (format already validated)."""
    year, month = value.split("-")
    return date(int(year), int(month), 1)


class BudgetSet(BaseModel):
    """Create or update the budget for a category in a month."""

    category_id: uuid.UUID
    month: str = Field(pattern=MONTH_PATTERN, examples=["2026-11"])
    limit_amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2, examples=["300.00"])
    currency: str = Field(pattern=r"^[A-Z]{3}$", examples=["GBP"])


class BudgetRead(BaseModel):
    """A budget with spend so far this month."""

    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str = Field(examples=["Eating out"])
    month: str = Field(examples=["2026-11"])
    limit_amount: Decimal = Field(examples=["300.00"])
    currency: str = Field(examples=["GBP"])
    spent: Decimal = Field(examples=["240.00"])
    remaining: Decimal = Field(examples=["60.00"], description="Negative when over budget.")
    percent_used: Decimal = Field(examples=["80.0"])
    status: Literal["ok", "warning", "exceeded"] = Field(
        description="warning at 80 % or more, exceeded at 100 % or more."
    )


class NotificationRead(BaseModel):
    """An in-app notification."""

    id: uuid.UUID
    kind: str = Field(examples=["budget_warning"])
    title: str = Field(examples=["80% of budget used: Eating out"])
    body: str
    created_at: datetime
    read_at: datetime | None
