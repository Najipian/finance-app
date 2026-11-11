"""FastAPI dependencies shared by routes (DB session, Redis, settings, current user)."""

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_app.core.config import Settings
from finance_app.modules.auth.service import AuthService, InvalidTokenError
from finance_app.modules.users.models import User

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
