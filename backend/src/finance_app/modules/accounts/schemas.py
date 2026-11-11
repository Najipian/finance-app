"""API schemas for accounts and balances (BR-05).

Amounts are ``Decimal`` and serialised as JSON strings (e.g. ``"1523.47"``) so no
precision is lost in transit.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from finance_app.modules.connections.models import ConnectionStatus


class BalanceRead(BaseModel):
    """One balance type of an account."""

    model_config = ConfigDict(from_attributes=True)

    type: str = Field(examples=["INTERIM_AVAILABLE"])
    amount: Decimal = Field(examples=["1523.47"])
    currency: str = Field(examples=["GBP"])
    as_of: datetime


class AccountRead(BaseModel):
    """An account with its headline balance and all reported balances."""

    id: uuid.UUID
    connection_id: uuid.UUID
    institution_name: str = Field(examples=["Mock Bank (UK)"])
    connection_status: ConnectionStatus
    name: str = Field(examples=["Everyday Current"])
    type: str = Field(examples=["CURRENT"])
    currency: str = Field(examples=["GBP"])
    account_number_masked: str | None = Field(examples=["•••• 5555"])
    balance: BalanceRead | None = Field(
        description="Headline balance: available if reported, otherwise booked."
    )
    balances: list[BalanceRead]


class CurrencyTotal(BaseModel):
    """Sum of headline balances in one currency (currencies are never mixed)."""

    currency: str = Field(examples=["GBP"])
    amount: Decimal = Field(examples=["9477.57"])
    account_count: int


class AccountsOverview(BaseModel):
    """Every account across all connected banks, plus totals per currency."""

    accounts: list[AccountRead]
    totals: list[CurrencyTotal]
