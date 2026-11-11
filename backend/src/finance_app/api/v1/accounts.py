"""Accounts across all connected banks (BR-05)."""

from fastapi import APIRouter, status

from finance_app.api.deps import AccountServiceDep, CurrentUser
from finance_app.core.errors import problem
from finance_app.modules.accounts.schemas import AccountsOverview

router = APIRouter(tags=["accounts"])


@router.get(
    "/accounts",
    summary="All accounts and balances",
    description=(
        "Every account across the user's connected banks with its headline balance "
        "(available if reported, otherwise booked), all reported balances, and a total "
        "per currency. Amounts are decimal strings."
    ),
    response_model=AccountsOverview,
    responses={status.HTTP_401_UNAUTHORIZED: problem("Missing, invalid or expired token.")},
)
async def list_accounts(user: CurrentUser, service: AccountServiceDep) -> AccountsOverview:
    """Return the user's accounts and per-currency totals."""
    return await service.overview(user.id)
