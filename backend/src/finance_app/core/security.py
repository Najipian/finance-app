"""Password hashing (Argon2id), access tokens (JWT) and refresh tokens (opaque).

Design notes:

- Argon2 is deliberately slow and CPU-bound, so hashing runs in a worker thread
  (``asyncio.to_thread``) instead of blocking the event loop.
- Access tokens are short-lived HS256 JWTs carrying only the user ID.
- Refresh tokens are random strings, not JWTs. Only their SHA-256 hash is stored.
  A fast hash is enough because the token has 256 bits of entropy; Argon2 is for
  low-entropy secrets such as passwords.
"""

import asyncio
import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from functools import cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from finance_app.core.config import Settings

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a claim value, not a secret
REFRESH_TOKEN_BYTES = 32

# argon2-cffi defaults to Argon2id with RFC 9106 "low memory" parameters.
_hasher = PasswordHasher()


class TokenError(Exception):
    """An access token is missing, malformed, expired or of the wrong type."""


async def hash_password(password: str) -> str:
    """Hash a password with Argon2id.

    Args:
        password: The plain-text password.

    Returns:
        The encoded hash, including algorithm, parameters and salt.
    """
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against a stored Argon2 hash.

    Args:
        password_hash: Hash previously produced by ``hash_password``.
        password: The candidate plain-text password.

    Returns:
        True if the password matches; False otherwise, including for a corrupt hash.
    """
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Whether a hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


@cache
def dummy_password_hash() -> str:
    """A fixed hash to verify against when the user does not exist.

    Verifying against it costs the same time as a real check, so login response
    times don't reveal which emails are registered.
    """
    return _hasher.hash(secrets.token_urlsafe(16))


def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    """Create a signed, short-lived access token for a user.

    Args:
        user_id: The authenticated user's ID (becomes the ``sub`` claim).
        settings: Provides the secret, algorithm and lifetime.

    Returns:
        The encoded JWT.
    """
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + settings.access_token_ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Validate an access token and return the user ID it was issued to.

    Args:
        token: The encoded JWT from the ``Authorization`` header.
        settings: Provides the secret and the single allowed algorithm.

    Returns:
        The user ID from the ``sub`` claim.

    Raises:
        TokenError: The token is invalid, expired, or not an access token.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # pinned: never trust the header's "alg"
            options={"require": ["sub", "exp", "iat", "type"]},
        )
        if claims["type"] != ACCESS_TOKEN_TYPE:
            raise TokenError("not an access token")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise TokenError(str(exc)) from exc


def new_refresh_token() -> str:
    """Generate a new opaque refresh token (URL-safe, 256 bits of entropy)."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage and lookup (hex SHA-256)."""
    return hashlib.sha256(token.encode()).hexdigest()
