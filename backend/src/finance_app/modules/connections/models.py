"""Bank connection ORM model."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from finance_app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConnectionStatus(StrEnum):
    """Lifecycle of a bank connection."""

    PENDING = "pending"  # consent started, user not back from the bank yet
    ACTIVE = "active"
    NEEDS_RENEWAL = "needs_renewal"  # consent expired or revoked at the bank
    REVOKED = "revoked"


class BankConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's consent-based link to one bank through a provider.

    ``consent_token_enc`` holds the provider consent token encrypted with
    AES-256-GCM, bound to this row's ID (see ``core/crypto.py``). It is never
    stored or logged in plain text.
    """

    __tablename__ = "bank_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    institution_id: Mapped[str] = mapped_column(String(128))
    institution_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(
            ConnectionStatus,
            native_enum=False,
            length=20,
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
            name="connection_status",
        )
    )
    consent_token_enc: Mapped[str | None] = mapped_column(Text)
    provider_consent_id: Mapped[str | None] = mapped_column(String(255))
    consent_expires_at: Mapped[datetime | None]
    last_synced_at: Mapped[datetime | None]
