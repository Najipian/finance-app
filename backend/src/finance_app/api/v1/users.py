"""Endpoints about the signed-in user."""

from fastapi import APIRouter, status

from finance_app.api.deps import CurrentUser
from finance_app.core.errors import problem
from finance_app.modules.users.schemas import UserRead

router = APIRouter(tags=["users"])


@router.get(
    "/me",
    summary="Current user",
    description="Returns the profile of the user the access token belongs to.",
    response_model=UserRead,
    responses={status.HTTP_401_UNAUTHORIZED: problem("Missing, invalid or expired token.")},
)
async def read_me(user: CurrentUser) -> UserRead:
    """Return the signed-in user's profile."""
    return UserRead.model_validate(user)
