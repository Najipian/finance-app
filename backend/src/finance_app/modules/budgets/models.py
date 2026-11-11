"""Budget ORM model."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from finance_app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Budget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A monthly spending limit for one category.

    ``month`` is the first day of the month. ``alerted_80`` / ``alerted_100`` make
    each threshold alert fire once (BR-10).
    """

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id", "month"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    month: Mapped[date]
    limit_amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    alerted_80: Mapped[bool] = mapped_column(default=False, server_default=false())
    alerted_100: Mapped[bool] = mapped_column(default=False, server_default=false())
