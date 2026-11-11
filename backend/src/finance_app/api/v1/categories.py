"""Categories and categorisation rules (BR-07, BR-08)."""

import uuid

from fastapi import APIRouter, Response, status

from finance_app.api.deps import CategoryServiceDep, CurrentUser
from finance_app.core.errors import problem
from finance_app.modules.categories.schemas import (
    CategoryCreate,
    CategoryRead,
    RuleCreate,
    RuleRead,
)

router = APIRouter(tags=["categories"])

_UNAUTHORIZED = problem("Missing, invalid or expired token.")
_NOT_FOUND = problem("No such category or rule for this user.")


@router.get(
    "/categories",
    summary="List categories",
    description="The 12 built-in categories plus the user's own.",
    response_model=list[CategoryRead],
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def list_categories(user: CurrentUser, service: CategoryServiceDep) -> list[CategoryRead]:
    """List categories available to the user."""
    return [
        CategoryRead(id=c.id, name=c.name, icon=c.icon, is_default=c.user_id is None)
        for c in await service.list_categories(user.id)
    ]


@router.post(
    "/categories",
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    response_model=CategoryRead,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_409_CONFLICT: problem("A category with this name already exists."),
    },
)
async def create_category(
    body: CategoryCreate, user: CurrentUser, service: CategoryServiceDep
) -> CategoryRead:
    """Create a user category."""
    category = await service.create_category(user.id, body.name, body.icon)
    return CategoryRead(id=category.id, name=category.name, icon=category.icon, is_default=False)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a category",
    description="Its rules are deleted and its transactions become Uncategorized.",
    response_class=Response,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_409_CONFLICT: problem("Built-in categories can't be deleted."),
    },
)
async def delete_category(
    category_id: uuid.UUID, user: CurrentUser, service: CategoryServiceDep
) -> Response:
    """Delete a user category."""
    await service.delete_category(user.id, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/category-rules",
    summary="List my rules",
    description="The user's own rules (built-in rules apply after them).",
    response_model=list[RuleRead],
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def list_rules(user: CurrentUser, service: CategoryServiceDep) -> list[RuleRead]:
    """List the user's rules."""
    return [RuleRead.model_validate(r) for r in await service.list_rules(user.id)]


@router.post(
    "/category-rules",
    status_code=status.HTTP_201_CREATED,
    summary="Create a rule",
    description="Applied immediately to existing transactions that weren't set by hand.",
    response_model=RuleRead,
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED, status.HTTP_404_NOT_FOUND: _NOT_FOUND},
)
async def create_rule(body: RuleCreate, user: CurrentUser, service: CategoryServiceDep) -> RuleRead:
    """Create a categorisation rule."""
    rule, _ = await service.create_rule(
        user.id, body.match_field, body.operator, body.value, body.category_id, body.priority
    )
    return RuleRead.model_validate(rule)


@router.delete(
    "/category-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a rule",
    response_class=Response,
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED, status.HTTP_404_NOT_FOUND: _NOT_FOUND},
)
async def delete_rule(
    rule_id: uuid.UUID, user: CurrentUser, service: CategoryServiceDep
) -> Response:
    """Delete one of the user's rules."""
    await service.delete_rule(user.id, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
