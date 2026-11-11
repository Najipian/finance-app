"""Monthly budgets per category (BR-09) with threshold status (BR-10)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from finance_app.api.deps import BudgetServiceDep, CurrentUser
from finance_app.core.errors import problem
from finance_app.modules.budgets.schemas import MONTH_PATTERN, BudgetRead, BudgetSet, parse_month
from finance_app.modules.budgets.service import BudgetView, budget_status, percent_used

router = APIRouter(tags=["budgets"])

_UNAUTHORIZED = problem("Missing, invalid or expired token.")


def _read(view: BudgetView) -> BudgetRead:
    budget = view.budget
    return BudgetRead(
        id=budget.id,
        category_id=budget.category_id,
        category_name=view.category_name,
        month=f"{budget.month:%Y-%m}",
        limit_amount=budget.limit_amount,
        currency=budget.currency,
        spent=view.spent,
        remaining=budget.limit_amount - view.spent,
        percent_used=percent_used(view.spent, budget.limit_amount),
        status=budget_status(view.spent, budget.limit_amount),  # type: ignore[arg-type]
    )


@router.get(
    "/budgets",
    summary="Budgets for a month",
    description="Each budget with spend so far, remaining amount and status.",
    response_model=list[BudgetRead],
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def list_budgets(
    user: CurrentUser,
    service: BudgetServiceDep,
    month: Annotated[str, Query(pattern=MONTH_PATTERN, examples=["2026-11"])],
) -> list[BudgetRead]:
    """List the user's budgets for a month."""
    return [_read(v) for v in await service.list(user.id, parse_month(month))]


@router.put(
    "/budgets",
    summary="Set a budget",
    description=(
        "Creates or updates the budget for a category and month. Alerts at 80 % and "
        "100 % are sent once each (BR-10); changing the limit re-checks them."
    ),
    response_model=BudgetRead,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: problem("No such category for this user."),
    },
)
async def set_budget(body: BudgetSet, user: CurrentUser, service: BudgetServiceDep) -> BudgetRead:
    """Create or update a monthly budget."""
    view = await service.set_budget(
        user.id, body.category_id, parse_month(body.month), body.limit_amount, body.currency
    )
    return _read(view)


@router.delete(
    "/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a budget",
    response_class=Response,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: problem("No such budget for this user."),
    },
)
async def delete_budget(
    budget_id: uuid.UUID, user: CurrentUser, service: BudgetServiceDep
) -> Response:
    """Delete one of the user's budgets."""
    await service.delete(user.id, budget_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
