"""Transaction ORM model."""

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from finance_app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TransactionStatus(StrEnum):
    """Whether the bank has settled the transaction."""

    BOOKED = "booked"
    PENDING = "pending"


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bank transaction. ``(account_id, dedup_key)`` is unique, so syncs never duplicate.

    No raw provider payload is stored: it holds personal data the app doesn't need
    (NFR-05).
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "dedup_key"),
        Index("ix_transactions_account_id_booking_date", "account_id", "booking_date"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255))
    dedup_key: Mapped[str] = mapped_column(String(64))
    booking_date: Mapped[date]
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(String(500))
    merchant: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(
            TransactionStatus,
            native_enum=False,
            length=10,
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
            name="transaction_status",
        )
    )
