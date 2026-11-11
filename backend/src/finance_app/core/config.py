"""Application settings, loaded from environment variables via pydantic-settings.

Every setting here must also be listed in the repository's ``.env.example``.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


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

    cors_origins: list[str] = Field(
        default_factory=list,
        description='Allowed web origins as a JSON list, e.g. ["http://localhost:5173"].',
    )

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
