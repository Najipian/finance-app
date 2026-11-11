"""Audit log ORM model."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finance_app.db.base import Base, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """One audited event. Append-only: a database trigger rejects UPDATE/DELETE/TRUNCATE.

    ``user_id`` is deliberately not a foreign key, so the trail survives deletion of
    the user. ``details`` holds IDs, outcomes and counts only, never personal data
    or secrets.
    """

    __tablename__ = "audit_log"

    # Strictly increasing insertion order. Timestamps can't order events written in
    # one transaction (Postgres now() is fixed per transaction); seq also makes gaps
    # detectable.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
