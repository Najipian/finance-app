"""Authentication endpoints (BR-01)."""

from fastapi import APIRouter, Response, status

from finance_app.api.deps import AuthServiceDep
from finance_app.core.errors import problem
from finance_app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)
from finance_app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_TOKEN = problem("The refresh token is unknown, expired or already used.")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description="Registers a user with an email and a password of 12-128 characters.",
    response_model=UserRead,
    responses={
        status.HTTP_409_CONFLICT: problem("An account with this email already exists."),
        status.HTTP_422_UNPROCESSABLE_CONTENT: problem("Invalid email or password length."),
    },
)
async def register(body: RegisterRequest, service: AuthServiceDep) -> UserRead:
    """Create a new user account."""
    user = await service.register(body.email, body.password.get_secret_value())
    return UserRead.model_validate(user)


@router.post(
    "/login",
    summary="Sign in",
    description=(
        "Exchanges email and password for a 15-minute access token and a single-use "
        "refresh token. Wrong email and wrong password give the same response."
    ),
    response_model=TokenPair,
    responses={status.HTTP_401_UNAUTHORIZED: problem("Incorrect email or password.")},
)
async def login(body: LoginRequest, service: AuthServiceDep) -> TokenPair:
    """Sign in and start a new session."""
    return await service.login(body.email, body.password.get_secret_value())


@router.post(
    "/refresh",
    summary="Rotate tokens",
    description=(
        "Exchanges a refresh token for a new token pair. The old refresh token stops "
        "working. Presenting an already-used token revokes the whole session."
    ),
    response_model=TokenPair,
    responses={status.HTTP_401_UNAUTHORIZED: _INVALID_TOKEN},
)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> TokenPair:
    """Rotate a refresh token."""
    return await service.refresh(body.refresh_token.get_secret_value())


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description="Revokes the session the refresh token belongs to. Always returns 204.",
    response_class=Response,
)
async def logout(body: RefreshRequest, service: AuthServiceDep) -> Response:
    """End the current session."""
    await service.logout(body.refresh_token.get_secret_value())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
