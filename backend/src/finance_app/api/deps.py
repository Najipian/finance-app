"""FastAPI dependencies shared by routes (DB session, Redis, settings, current user)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_app.core.config import Settings
from finance_app.core.crypto import TokenCipher
from finance_app.core.jobs import JobQueue
from finance_app.core.rate_limit import RateLimit, RateLimiter
from finance_app.modules.accounts.service import AccountService
from finance_app.modules.auth.service import AuthService, InvalidTokenError
from finance_app.modules.connections.service import ConnectionService
from finance_app.modules.connections.state import ConsentStateStore
from finance_app.modules.users.models import User
from finance_app.providers.base import BankProvider

# auto_error=False so a missing header becomes our own RFC 9457 401, not FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from POST /auth/login.")


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for one request, closed afterwards.

    Args:
        request: The current request; the session factory lives on ``app.state``.

    Yields:
        An ``AsyncSession``. Services decide when to commit.
    """
    sessionmaker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with sessionmaker() as session:
        yield session


def get_redis(request: Request) -> Redis:
    """Return the app-wide Redis client created at startup.

    Args:
        request: The current request.

    Returns:
        The shared ``Redis`` client.
    """
    return cast(Redis, request.app.state.redis)


def get_app_settings(request: Request) -> Settings:
    """Return the settings the app was created with.

    Args:
        request: The current request.

    Returns:
        The ``Settings`` passed to ``create_app``.
    """
    return cast(Settings, request.app.state.settings)


DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


def get_rate_limiter(request: Request) -> RateLimiter:
    """Return the app-wide rate limiter created at startup."""
    return cast(RateLimiter, request.app.state.rate_limiter)


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    """The client's IP address.

    Behind a reverse proxy this is only correct when uvicorn runs with
    ``--proxy-headers`` and the proxy is listed in ``FORWARDED_ALLOW_IPS``.
    """
    return request.client.host if request.client else "unknown"


def limit_per_ip(endpoint: str) -> Callable[..., Awaitable[None]]:
    """Build a dependency that limits one endpoint per client IP.

    Args:
        endpoint: Short name used in the Redis key, e.g. ``"login"``.

    Returns:
        A FastAPI dependency raising ``RateLimitedError`` (429) over the limit.
    """

    async def dependency(request: Request, limiter: RateLimiterDep, settings: AppSettings) -> None:
        limit = RateLimit(requests=settings.auth_rate_limit_per_minute, window_seconds=60)
        await limiter.hit(f"{endpoint}:ip:{client_ip(request)}", limit)

    return dependency


def get_auth_service(db: DbSession, settings: AppSettings) -> AuthService:
    """Build the auth service for this request."""
    return AuthService(db, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Authenticate the request from its bearer access token.

    Args:
        service: Auth service used to validate the token.
        credentials: The parsed ``Authorization: Bearer`` header, if any.

    Returns:
        The authenticated user.

    Raises:
        InvalidTokenError: No token, or the token is invalid or expired (401).
    """
    if credentials is None:
        raise InvalidTokenError("Missing bearer token.")
    return await service.user_from_access_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_connection_service(
    request: Request, db: DbSession, settings: AppSettings
) -> ConnectionService:
    """Build the connection service with the app-wide provider, cipher and queues."""
    state = request.app.state
    return ConnectionService(
        session=db,
        provider=cast(BankProvider, state.provider),
        cipher=cast(TokenCipher, state.cipher),
        states=cast(ConsentStateStore, state.consent_states),
        jobs=cast(JobQueue, state.job_queue),
        settings=settings,
    )


ConnectionServiceDep = Annotated[ConnectionService, Depends(get_connection_service)]


def get_account_service(db: DbSession) -> AccountService:
    """Build the account service for this request."""
    return AccountService(db)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
