"""User ORM model."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from finance_app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMAIL_MAX_LENGTH = 320  # RFC 5321 limit for a full address


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered user. ``email`` is unique and always stored lower-case."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
