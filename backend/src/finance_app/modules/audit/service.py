"""Recording and reading audit events (NFR-06).

Events are added to the caller's session, so they commit (or roll back) together
with the change they describe. Never put personal data or secrets in ``details``.
"""

import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.audit.models import AuditEvent


class AuditAction(StrEnum):
    """What happened. ``entity.verb`` naming."""

    CONSENT_STARTED = "consent.started"
    CONSENT_GRANTED = "consent.granted"
    CONSENT_RENEWED = "consent.renewed"
    CONSENT_NOT_GRANTED = "consent.not_granted"
    CONSENT_EXPIRED = "consent.expired"
    CONSENT_REVOKED = "consent.revoked"
    CONNECTION_DELETED = "connection.deleted"
    SYNC_SUCCEEDED = "sync.succeeded"
    SYNC_FAILED = "sync.failed"


class AuditService:
    """Append and read audit events.

    Args:
        session: The session of the change being audited; the caller commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        action: AuditAction,
        *,
        user_id: uuid.UUID | None,
        entity: str,
        entity_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Stage an audit event in the current transaction."""
        self._session.add(
            AuditEvent(
                user_id=user_id,
                action=action.value,
                entity=entity,
                entity_id=entity_id,
                details=details or {},
            )
        )

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[AuditEvent], int]:
        """The user's own events, newest first, and the total count."""
        query = select(AuditEvent).where(AuditEvent.user_id == user_id)
        total = (
            await self._session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        page = await self._session.execute(
            query.order_by(AuditEvent.seq.desc()).limit(limit).offset(offset)
        )
        return page.scalars().all(), int(total)
