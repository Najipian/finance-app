"""In-app notifications (BR-10)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.errors import NotFoundError
from finance_app.modules.notifications.models import Notification


class NotificationService:
    """Creates and reads a user's notifications.

    Args:
        session: Database session; ``notify`` leaves committing to the caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def notify(self, user_id: uuid.UUID, kind: str, title: str, body: str) -> Notification:
        """Stage a notification for the user."""
        notification = Notification(user_id=user_id, kind=kind, title=title, body=body)
        self._session.add(notification)
        return notification

    async def list(self, user_id: uuid.UUID, *, unread_only: bool) -> Sequence[Notification]:
        """The user's notifications, newest first (at most 100)."""
        query = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        result = await self._session.execute(
            query.order_by(Notification.created_at.desc()).limit(100)
        )
        return result.scalars().all()

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
        """Mark one of the user's notifications as read.

        Raises:
            NotFoundError: Not found for this user.
        """
        result = await self._session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            raise NotFoundError("Notification not found.")
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            await self._session.commit()
        return notification
