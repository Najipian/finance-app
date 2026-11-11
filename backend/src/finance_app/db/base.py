"""SQLAlchemy declarative base and shared column mixins.

Conventions enforced here so every model gets them for free:

- Constraint names are deterministic, so Alembic autogenerate produces stable diffs.
- ``datetime`` columns are timezone-aware; ``Decimal`` columns are ``NUMERIC(18, 2)``.
- Primary keys are UUIDs.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, MetaData, Numeric, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this class attribute
        datetime: DateTime(timezone=True),
        Decimal: Numeric(18, 2),
    }


class UUIDPrimaryKeyMixin:
    """Adds a random UUID primary key named ``id``."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` set by the database in UTC."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
