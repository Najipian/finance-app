"""API schemas for transactions (BR-06). Amounts are decimal strings; debits are negative."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from finance_app.modules.transactions.models import CategorySource, TransactionStatus


class TransactionRead(BaseModel):
    """One transaction."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    booking_date: date
    amount: Decimal = Field(examples=["-12.50"])
    currency: str = Field(examples=["GBP"])
    description: str = Field(examples=["PRET A MANGER LONDON"])
    merchant: str | None = Field(examples=["Pret A Manger"])
    status: TransactionStatus
    category_id: uuid.UUID | None = Field(description="None means Uncategorized.")
    category_source: CategorySource | None = Field(
        description="rule (automatic) or manual (set by the user; rules never change it)."
    )


class TransactionPage(BaseModel):
    """A page of transactions, newest first."""

    items: list[TransactionRead]
    total: int = Field(description="Matching transactions across all pages.")
    limit: int
    offset: int


class RecategorizeRequest(BaseModel):
    """Change a transaction's category (BR-08)."""

    category_id: uuid.UUID | None = Field(description="None sets Uncategorized.")
    apply_to_similar: bool = Field(
        default=False,
        description=(
            "Also create a rule (merchant, else description, equals this transaction's) "
            "and apply it to past and future transactions."
        ),
    )


class RecategorizeResult(BaseModel):
    """The updated transaction and, if requested, the rule that was created."""

    transaction: TransactionRead
    rule_id: uuid.UUID | None
    similar_updated: int = Field(description="Other transactions re-categorised by the rule.")
