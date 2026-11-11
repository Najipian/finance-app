"""Application settings, loaded from environment variables via pydantic-settings.

Every setting here must also be listed in the repository's ``.env.example``.
"""

from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from finance_app.core.crypto import decode_key

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
MIN_JWT_SECRET_LENGTH = 32


class Environment(StrEnum):
    """Deployment environment the app is running in."""

    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed application configuration.

    Values come from environment variables (case-insensitive) and, for local
    development, from a ``.env`` file at the repo root or in ``backend/``.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Finance App", description="Name shown in OpenAPI docs.")
    environment: Environment = Field(default=Environment.LOCAL)
    log_level: LogLevel = Field(default="INFO")

    # Postgres is configured in parts (not one DSN) so the password stays a SecretStr
    # and never appears in reprs or logs. The same names configure the postgres container.
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="finance")
    postgres_password: SecretStr = Field(description="Required; no default on purpose.")
    postgres_db: str = Field(default="finance_app")

    redis_url: str = Field(default="redis://localhost:6379/0")

    # Auth (BR-01). Access tokens are short-lived JWTs; refresh tokens are opaque,
    # stored hashed and rotated on every use.
    jwt_secret: SecretStr = Field(description="HMAC key for access tokens; required, 32+ chars.")
    jwt_algorithm: Literal["HS256"] = Field(default="HS256")
    access_token_ttl_minutes: int = Field(default=15, gt=0)
    refresh_token_ttl_days: int = Field(default=7, gt=0)

    # Rate limiting (NFR-02/03, ADR 0002). Fixed windows counted in Redis.
    rate_limit_enabled: bool = Field(default=True)
    auth_rate_limit_per_minute: int = Field(
        default=10, gt=0, description="Requests per minute per client IP, per auth endpoint."
    )
    login_account_rate_limit: int = Field(
        default=5, gt=0, description="Login attempts per account per window, from any IP."
    )
    login_account_window_seconds: int = Field(default=900, gt=0)

    # Encryption of bank secrets at rest (NFR-01). Base64 of 32 random bytes.
    token_encryption_key: SecretStr = Field(description="Required; AES-256-GCM key.")
    token_encryption_key_version: int = Field(default=1, gt=0)
    token_encryption_retired_keys: dict[int, SecretStr] = Field(
        default_factory=dict,
        description='Older keys still accepted for decryption, e.g. {"1": "<base64>"}.',
    )

    # Open Banking provider (BR-02). "mock" works offline with a demo bank page.
    bank_provider: Literal["mock", "yapily"] = Field(default="mock")
    yapily_base_url: str = Field(default="https://api.yapily.com")
    yapily_application_uuid: str | None = Field(default=None)
    yapily_application_secret: SecretStr | None = Field(default=None)
    provider_timeout_seconds: float = Field(default=15.0, gt=0)

    # Public URLs used in redirects during the bank consent flow.
    public_api_url: str = Field(
        default="http://localhost:8000", description="Where browsers reach this API."
    )
    web_app_url: str = Field(
        default="http://localhost:5173", description="Where the user lands after consent."
    )
    consent_state_ttl_seconds: int = Field(default=600, gt=0)

    cors_origins: list[str] = Field(
        default_factory=list,
        description='Allowed web origins as a JSON list, e.g. ["http://localhost:5173"].',
    )

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        """Reject short HMAC keys: HS256 needs at least 256 bits of key material."""
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            msg = f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters"
            raise ValueError(msg)
        return value

    @field_validator("token_encryption_key")
    @classmethod
    def _encryption_key_is_256_bits(cls, value: SecretStr) -> SecretStr:
        """Fail at startup, not at first use, if the key is malformed."""
        try:
            decode_key(value.get_secret_value())
        except ValueError as exc:
            msg = f"TOKEN_ENCRYPTION_KEY: {exc}"
            raise ValueError(msg) from exc
        return value

    @model_validator(mode="after")
    def _yapily_needs_credentials(self) -> "Settings":
        """Refuse to start with the Yapily provider but no credentials."""
        if self.bank_provider == "yapily" and not (
            self.yapily_application_uuid and self.yapily_application_secret
        ):
            msg = "BANK_PROVIDER=yapily needs YAPILY_APPLICATION_UUID and _SECRET"
            raise ValueError(msg)
        return self

    def encryption_keys(self) -> dict[int, bytes]:
        """All usable encryption keys by version (current plus retired)."""
        keys = {
            v: decode_key(k.get_secret_value())
            for v, k in self.token_encryption_retired_keys.items()
        }
        keys[self.token_encryption_key_version] = decode_key(
            self.token_encryption_key.get_secret_value()
        )
        return keys

    @property
    def access_token_ttl(self) -> timedelta:
        """Lifetime of an access token."""
        return timedelta(minutes=self.access_token_ttl_minutes)

    @property
    def refresh_token_ttl(self) -> timedelta:
        """Lifetime of a refresh token."""
        return timedelta(days=self.refresh_token_ttl_days)

    @property
    def database_url(self) -> URL:
        """Async SQLAlchemy URL for asyncpg. Its ``repr`` masks the password."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def is_production(self) -> bool:
        """Whether the app runs in production (JSON logs, stricter defaults)."""
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment once.

    Returns:
        The cached ``Settings`` instance. Tests pass their own ``Settings`` to
        ``create_app`` instead of relying on this cache.
    """
    return Settings()
