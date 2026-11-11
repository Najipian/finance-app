"""Consent lifecycle checks run on a schedule (BR-03).

- ``check_expiry``: connections whose consent has expired become ``needs_renewal``,
  which stops syncing (US-02: "sync stops and the bank is marked Needs renewal").
- ``renewal_due``: whether to show the renew banner (US-02: expires in 7 days or
  less). Computed at read time from ``consent_expires_at``, so it is always exact.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.audit.service import AuditAction, AuditService
from finance_app.modules.connections.models import BankConnection, ConnectionStatus

RENEWAL_WARNING = timedelta(days=7)

log = structlog.get_logger(__name__)


def renewal_due(expires_at: datetime | None, now: datetime) -> bool:
    """Whether a consent expires within the warning period (or already has)."""
    return expires_at is not None and expires_at - now <= RENEWAL_WARNING


def days_until(expires_at: datetime | None, now: datetime) -> int | None:
    """Whole days until expiry (negative once expired), or None if unknown."""
    if expires_at is None:
        return None
    return (expires_at - now).days


@dataclass(frozen=True, slots=True)
class ExpiryReport:
    """Outcome of one expiry check."""

    expired: int
    expiring_soon: int


class ConsentLifecycleService:
    """Scheduled consent maintenance.

    Args:
        session: Database session owned by the job.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_expiry(self, now: datetime) -> ExpiryReport:
        """Mark expired consents ``needs_renewal`` and count those expiring soon."""
        expired = await self._session.execute(
            update(BankConnection)
            .where(
                BankConnection.status == ConnectionStatus.ACTIVE,
                BankConnection.consent_expires_at <= now,
            )
            .values(status=ConnectionStatus.NEEDS_RENEWAL)
            .returning(BankConnection.id, BankConnection.user_id)
        )
        expired_rows = expired.all()
        expired_ids = [row.id for row in expired_rows]
        audit = AuditService(self._session)
        for row in expired_rows:
            audit.record(
                AuditAction.CONSENT_EXPIRED,
                user_id=row.user_id,
                entity="connection",
                entity_id=row.id,
                details={"detected_by": "daily_check"},
            )
        soon = await self._session.execute(
            select(BankConnection.id).where(
                BankConnection.status == ConnectionStatus.ACTIVE,
                BankConnection.consent_expires_at <= now + RENEWAL_WARNING,
            )
        )
        expiring_soon = len(soon.scalars().all())
        await self._session.commit()
        for connection_id in expired_ids:
            log.info("consent_expired", connection_id=str(connection_id))
        return ExpiryReport(expired=len(expired_ids), expiring_soon=expiring_soon)

    async def active_connection_ids(self) -> Sequence[uuid.UUID]:
        """IDs of connections that should be synced on schedule."""
        result = await self._session.execute(
            select(BankConnection.id).where(BankConnection.status == ConnectionStatus.ACTIVE)
        )
        return result.scalars().all()
