"""Authentication endpoints (BR-01)."""

from fastapi import APIRouter, Depends, Response, status

from finance_app.api.deps import AppSettings, AuthServiceDep, RateLimiterDep, limit_per_ip
from finance_app.core.errors import problem
from finance_app.core.rate_limit import RateLimit, hashed_key_part
from finance_app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)
from finance_app.modules.auth.service import normalize_email
from finance_app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_TOKEN = problem("The refresh token is unknown, expired or already used.")
_RATE_LIMITED = problem("Too many attempts; retry after the `Retry-After` seconds.")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description="Registers a user with an email and a password of 12-128 characters.",
    response_model=UserRead,
    dependencies=[Depends(limit_per_ip("register"))],
    responses={
        status.HTTP_409_CONFLICT: problem("An account with this email already exists."),
        status.HTTP_422_UNPROCESSABLE_CONTENT: problem("Invalid email or password length."),
        status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMITED,
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
        "refresh token. Wrong email and wrong password give the same response. "
        "Limited per client IP and per account (from any IP) to slow password guessing."
    ),
    response_model=TokenPair,
    dependencies=[Depends(limit_per_ip("login"))],
    responses={
        status.HTTP_401_UNAUTHORIZED: problem("Incorrect email or password."),
        status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMITED,
    },
)
async def login(
    body: LoginRequest,
    service: AuthServiceDep,
    limiter: RateLimiterDep,
    settings: AppSettings,
) -> TokenPair:
    """Sign in and start a new session."""
    account_limit = RateLimit(
        requests=settings.login_account_rate_limit,
        window_seconds=settings.login_account_window_seconds,
    )
    account = hashed_key_part(normalize_email(body.email))
    await limiter.hit(f"login:account:{account}", account_limit)
    return await service.login(body.email, body.password.get_secret_value())


@router.post(
    "/refresh",
    summary="Rotate tokens",
    description=(
        "Exchanges a refresh token for a new token pair. The old refresh token stops "
        "working. Presenting an already-used token revokes the whole session."
    ),
    response_model=TokenPair,
    dependencies=[Depends(limit_per_ip("refresh"))],
    responses={
        status.HTTP_401_UNAUTHORIZED: _INVALID_TOKEN,
        status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMITED,
    },
)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> TokenPair:
    """Rotate a refresh token."""
    return await service.refresh(body.refresh_token.get_secret_value())


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description="Revokes the session the refresh token belongs to. Returns 204.",
    response_class=Response,
    dependencies=[Depends(limit_per_ip("logout"))],
    responses={status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMITED},
)
async def logout(body: RefreshRequest, service: AuthServiceDep) -> Response:
    """End the current session."""
    await service.logout(body.refresh_token.get_secret_value())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
