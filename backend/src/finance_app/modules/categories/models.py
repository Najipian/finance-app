"""Category and category rule ORM models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from finance_app.db.base import Base, UUIDPrimaryKeyMixin


def _enum(enum_cls: type[StrEnum], name: str, length: int) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        name=name,
    )


class Category(UUIDPrimaryKeyMixin, Base):
    """A spending category. ``user_id`` NULL means a built-in default for everyone."""

    __tablename__ = "categories"
    __table_args__ = (
        # NULLS NOT DISTINCT (Postgres 15+): default names are unique too.
        UniqueConstraint("user_id", "name", postgresql_nulls_not_distinct=True),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    icon: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RuleField(StrEnum):
    """Transaction field a rule looks at."""

    DESCRIPTION = "description"
    MERCHANT = "merchant"


class RuleOperator(StrEnum):
    """How a rule compares (always case-insensitive)."""

    CONTAINS = "contains"
    EQUALS = "equals"
    STARTS_WITH = "starts_with"


class CategoryRule(UUIDPrimaryKeyMixin, Base):
    """Rule: if <field> <operator> <value>, assign <category>. ``user_id`` NULL = built-in.

    User rules are evaluated before built-in ones; within each, lower ``priority``
    first, then newest first.
    """

    __tablename__ = "category_rules"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    match_field: Mapped[RuleField] = mapped_column(_enum(RuleField, "rule_field", 20))
    operator: Mapped[RuleOperator] = mapped_column(_enum(RuleOperator, "rule_operator", 20))
    value: Mapped[str] = mapped_column(String(100))
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    priority: Mapped[int] = mapped_column(default=100)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
