"""API schemas for authentication (BR-01)."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, SecretStr

PASSWORD_MIN_LENGTH = 12
# Upper bound so a huge "password" can't be used to burn CPU in Argon2.
PASSWORD_MAX_LENGTH = 128
REFRESH_TOKEN_MAX_LENGTH = 256


class RegisterRequest(BaseModel):
    """New account details."""

    email: EmailStr = Field(examples=["sara@example.com"])
    password: SecretStr = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description=f"{PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters.",
        examples=["correct-horse-battery-staple"],
    )


class LoginRequest(BaseModel):
    """Credentials to exchange for tokens."""

    email: EmailStr = Field(examples=["sara@example.com"])
    password: SecretStr = Field(
        max_length=PASSWORD_MAX_LENGTH, examples=["correct-horse-battery-staple"]
    )


class RefreshRequest(BaseModel):
    """A refresh token to rotate or revoke."""

    refresh_token: SecretStr = Field(max_length=REFRESH_TOKEN_MAX_LENGTH)


class TokenPair(BaseModel):
    """Tokens issued on login and refresh."""

    access_token: str = Field(description="JWT; send as `Authorization: Bearer <token>`.")
    refresh_token: str = Field(description="Opaque; single use. Exchange at /auth/refresh.")
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int = Field(description="Access token lifetime in seconds.", examples=[900])
