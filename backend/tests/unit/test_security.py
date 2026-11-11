"""Password hashing and token helpers (BR-01, NFR-02)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from finance_app.core.config import Settings
from finance_app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)


async def test_password_hash_is_argon2id_and_verifies_br01() -> None:
    hashed = await hash_password("correct-horse-battery")

    assert hashed.startswith("$argon2id$")
    assert await verify_password(hashed, "correct-horse-battery")
    assert not await verify_password(hashed, "wrong-password")
    assert not password_needs_rehash(hashed)


async def test_verify_password_returns_false_for_corrupt_hash() -> None:
    assert not await verify_password("not-a-hash", "anything")


def test_access_token_round_trip_br01(settings: Settings) -> None:
    user_id = uuid.uuid4()

    token = create_access_token(user_id, settings)

    assert decode_access_token(token, settings) == user_id


def _secret(settings: Settings) -> str:
    return settings.jwt_secret.get_secret_value()


def test_expired_access_token_is_rejected(settings: Settings) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": past, "exp": past},
        _secret(settings),
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_token_signed_with_other_key_is_rejected(settings: Settings) -> None:
    token = create_access_token(uuid.uuid4(), settings)
    forged = settings.model_copy(update={"jwt_secret": settings.jwt_secret.__class__("y" * 40)})

    with pytest.raises(TokenError):
        decode_access_token(token, forged)


def test_unsigned_alg_none_token_is_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_non_access_token_type_is_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        _secret(settings),
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_token_with_non_uuid_subject_is_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "admin", "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        _secret(settings),
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_refresh_tokens_are_random_and_hashed_deterministically() -> None:
    first, second = new_refresh_token(), new_refresh_token()

    assert first != second
    assert len(first) >= 43  # 32 bytes, URL-safe base64
    assert hash_refresh_token(first) == hash_refresh_token(first)
    assert len(hash_refresh_token(first)) == 64


def test_short_jwt_secret_is_rejected_at_startup() -> None:
    from pydantic import SecretStr, ValidationError

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            postgres_password=SecretStr("x"),
            jwt_secret=SecretStr("too-short"),
        )
