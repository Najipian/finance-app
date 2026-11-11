"""In-app notifications such as budget alerts (BR-10)."""

import uuid

from fastapi import APIRouter, status

from finance_app.api.deps import CurrentUser, NotificationServiceDep
from finance_app.core.errors import problem
from finance_app.modules.budgets.schemas import NotificationRead

router = APIRouter(tags=["notifications"])


@router.get(
    "/notifications",
    summary="List notifications",
    description="Newest first, at most 100. `unread=true` returns only unread ones.",
    response_model=list[NotificationRead],
    responses={status.HTTP_401_UNAUTHORIZED: problem("Missing, invalid or expired token.")},
)
async def list_notifications(
    user: CurrentUser, service: NotificationServiceDep, unread: bool = False
) -> list[NotificationRead]:
    """List the user's notifications."""
    return [
        NotificationRead.model_validate(n, from_attributes=True)
        for n in await service.list(user.id, unread_only=unread)
    ]


@router.post(
    "/notifications/{notification_id}/read",
    summary="Mark as read",
    response_model=NotificationRead,
    responses={
        status.HTTP_401_UNAUTHORIZED: problem("Missing, invalid or expired token."),
        status.HTTP_404_NOT_FOUND: problem("No such notification for this user."),
    },
)
async def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, service: NotificationServiceDep
) -> NotificationRead:
    """Mark one notification as read."""
    notification = await service.mark_read(user.id, notification_id)
    return NotificationRead.model_validate(notification, from_attributes=True)
