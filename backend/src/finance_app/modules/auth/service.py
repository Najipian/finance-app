"""Authentication business logic (BR-01).

Registration, login, refresh-token rotation with reuse detection, logout, and
resolving an access token to a user. Raises domain errors; never imports FastAPI.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Settings
from finance_app.core.errors import ConflictError, UnauthorizedError
from finance_app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    dummy_password_hash,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from finance_app.modules.auth.models import RefreshToken
from finance_app.modules.auth.repository import RefreshTokenRepository
from finance_app.modules.auth.schemas import TokenPair
from finance_app.modules.users.models import User
from finance_app.modules.users.repository import UserRepository

log = structlog.get_logger(__name__)


class EmailAlreadyRegisteredError(ConflictError):
    """Registration with an email that already has an account."""

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class InvalidCredentialsError(UnauthorizedError):
    """Wrong email or password. Deliberately doesn't say which."""

    def __init__(self) -> None:
        super().__init__("Incorrect email or password.")


class InvalidTokenError(UnauthorizedError):
    """A token is missing, invalid, expired or revoked."""

    def __init__(self, detail: str = "Invalid or expired token.") -> None:
        super().__init__(detail)


def normalize_email(email: str) -> str:
    """Trim and lower-case an email so lookups and uniqueness are case-insensitive."""
    return email.strip().lower()


class AuthService:
    """Use cases for registering, signing in and managing sessions.

    Args:
        session: Database session for this request; the service commits.
        settings: Token secrets and lifetimes.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    async def register(self, email: str, password: str) -> User:
        """Create a new user account.

        Args:
            email: The user's email (normalised before storage).
            password: The plain-text password (validated for length by the schema).

        Returns:
            The new user.

        Raises:
            EmailAlreadyRegisteredError: The email is already taken.
        """
        email = normalize_email(email)
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError
        user = User(email=email, password_hash=await hash_password(password))
        self._users.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:  # lost a race with a concurrent registration
            await self._session.rollback()
            raise EmailAlreadyRegisteredError from exc
        log.info("user_registered", user_id=str(user.id))
        return user

    async def login(self, email: str, password: str) -> TokenPair:
        """Verify credentials and start a new session (token family).

        Args:
            email: The email the user registered with (any case).
            password: The plain-text password.

        Returns:
            A new access + refresh token pair.

        Raises:
            InvalidCredentialsError: Unknown email or wrong password.
        """
        user = await self._users.get_by_email(normalize_email(email))
        if user is None:
            await verify_password(dummy_password_hash(), password)  # equalise timing
            raise InvalidCredentialsError
        if not await verify_password(user.password_hash, password):
            raise InvalidCredentialsError
        if password_needs_rehash(user.password_hash):
            user.password_hash = await hash_password(password)

        tokens = self._issue_tokens(user.id, family_id=uuid.uuid4())
        await self._session.commit()
        log.info("user_logged_in", user_id=str(user.id))
        return tokens

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Rotate a refresh token: revoke it and issue a new pair in the same family.

        Args:
            refresh_token: The opaque refresh token the client holds.

        Returns:
            A new access + refresh token pair.

        Raises:
            InvalidTokenError: Unknown, expired or already-used token. Reuse of a
                revoked token also revokes the whole family.
        """
        now = datetime.now(UTC)
        record = await self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if record is None:
            raise InvalidTokenError
        if record.revoked_at is not None:
            await self._tokens.revoke_family(record.family_id, now)
            await self._session.commit()
            log.warning(
                "refresh_token_reuse_detected",
                user_id=str(record.user_id),
                family_id=str(record.family_id),
            )
            raise InvalidTokenError
        if record.expires_at <= now:
            raise InvalidTokenError

        record.revoked_at = now
        tokens = self._issue_tokens(record.user_id, family_id=record.family_id)
        await self._session.commit()
        return tokens

    async def logout(self, refresh_token: str) -> None:
        """End the session the refresh token belongs to. Unknown tokens are ignored.

        Args:
            refresh_token: The opaque refresh token the client holds.
        """
        record = await self._tokens.get_by_hash_for_update(hash_refresh_token(refresh_token))
        if record is None:
            return
        await self._tokens.revoke_family(record.family_id, datetime.now(UTC))
        await self._session.commit()
        log.info("user_logged_out", user_id=str(record.user_id))

    async def user_from_access_token(self, access_token: str) -> User:
        """Resolve a bearer access token to its user.

        Args:
            access_token: The JWT from the ``Authorization`` header.

        Returns:
            The authenticated user.

        Raises:
            InvalidTokenError: The token is invalid or the user no longer exists.
        """
        try:
            user_id = decode_access_token(access_token, self._settings)
        except TokenError as exc:
            raise InvalidTokenError from exc
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError
        return user

    def _issue_tokens(self, user_id: uuid.UUID, family_id: uuid.UUID) -> TokenPair:
        """Create an access token and stage a hashed refresh token for insert."""
        raw_refresh = new_refresh_token()
        self._tokens.add(
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=hash_refresh_token(raw_refresh),
                expires_at=datetime.now(UTC) + self._settings.refresh_token_ttl,
            )
        )
        return TokenPair(
            access_token=create_access_token(user_id, self._settings),
            refresh_token=raw_refresh,
            expires_in=int(self._settings.access_token_ttl.total_seconds()),
        )
