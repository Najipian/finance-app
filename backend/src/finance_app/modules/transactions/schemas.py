"""API schemas for transactions (BR-06). Amounts are decimal strings; debits are negative."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from finance_app.modules.transactions.models import TransactionStatus


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


class TransactionPage(BaseModel):
    """A page of transactions, newest first."""

    items: list[TransactionRead]
    total: int = Field(description="Matching transactions across all pages.")
    limit: int
    offset: int
