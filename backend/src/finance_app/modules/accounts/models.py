"""Account and balance ORM models."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance_app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from finance_app.modules.connections.models import BankConnection


class Account(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bank account under a connection. Unique per provider account ID."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("connection_id", "provider_account_id"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"), index=True
    )
    provider_account_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3))
    account_number_masked: Mapped[str | None] = mapped_column(String(32))

    connection: Mapped[BankConnection] = relationship(lazy="raise")
    balances: Mapped[list["Balance"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Balance(UUIDPrimaryKeyMixin, Base):
    """The latest value of one balance type for an account (upserted each sync)."""

    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("account_id", "type"),)

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    as_of: Mapped[datetime]

    account: Mapped[Account] = relationship(back_populates="balances")
