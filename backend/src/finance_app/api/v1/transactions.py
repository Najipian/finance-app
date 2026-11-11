"""Transactions across all connected banks (BR-06)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from finance_app.api.deps import CurrentUser, TransactionServiceDep
from finance_app.core.errors import problem
from finance_app.modules.transactions.models import TransactionStatus
from finance_app.modules.transactions.repository import TransactionFilter
from finance_app.modules.transactions.schemas import TransactionPage

router = APIRouter(tags=["transactions"])


@router.get(
    "/transactions",
    summary="List transactions",
    description=(
        "The user's transactions across all banks, newest first. Filter by account, "
        "booking date range, status, or text in the description or merchant. "
        "Amounts are decimal strings; debits are negative."
    ),
    response_model=TransactionPage,
    responses={status.HTTP_401_UNAUTHORIZED: problem("Missing, invalid or expired token.")},
)
async def list_transactions(
    user: CurrentUser,
    service: TransactionServiceDep,
    account_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: Annotated[TransactionStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> TransactionPage:
    """Return a filtered page of the user's transactions."""
    filters = TransactionFilter(
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
        status=status_filter,
        text=q,
    )
    return await service.list(user.id, filters, limit=limit, offset=offset)
