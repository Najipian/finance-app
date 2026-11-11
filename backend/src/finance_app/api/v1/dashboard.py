"""Dashboard summary (BR-11) and the user's audit trail (NFR-06)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from finance_app.api.deps import CurrentUser, DbSession
from finance_app.core.errors import problem
from finance_app.modules.audit.service import AuditService
from finance_app.modules.budgets.schemas import MONTH_PATTERN, parse_month
from finance_app.modules.dashboard.schemas import DashboardSummary
from finance_app.modules.dashboard.service import DashboardService

router = APIRouter(tags=["dashboard"])

_UNAUTHORIZED = problem("Missing, invalid or expired token.")


@router.get(
    "/dashboard/summary",
    summary="Dashboard summary",
    description=(
        "Per currency: this month's spending by category (largest first) and the six-month "
        "trend of spending and income. Transfers between own accounts are excluded. "
        "Defaults to the current month."
    ),
    response_model=DashboardSummary,
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def dashboard_summary(
    user: CurrentUser,
    db: DbSession,
    month: Annotated[str | None, Query(pattern=MONTH_PATTERN, examples=["2026-11"])] = None,
) -> DashboardSummary:
    """Return dashboard data for a month."""
    target = parse_month(month) if month else datetime.now(UTC).date()
    return await DashboardService(db).summary(user.id, target)


class AuditEventRead(BaseModel):
    """One event in the user's audit trail."""

    model_config = ConfigDict(from_attributes=True)

    action: str = Field(examples=["consent.granted"])
    entity: str = Field(examples=["connection"])
    entity_id: uuid.UUID | None
    details: dict[str, Any]
    created_at: datetime


class AuditPage(BaseModel):
    """A page of audit events, newest first."""

    items: list[AuditEventRead]
    total: int


@router.get(
    "/audit-log",
    summary="My audit trail",
    description="Consent, sync and deletion events for the signed-in user (NFR-06).",
    response_model=AuditPage,
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def audit_log(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    """Return the user's audit events."""
    items, total = await AuditService(db).list_for_user(user.id, limit=limit, offset=offset)
    return AuditPage(items=[AuditEventRead.model_validate(i) for i in items], total=total)
