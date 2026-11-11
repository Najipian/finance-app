"""Alembic migration environment (async, asyncpg).

The URL comes from ``config.attributes["database_url"]`` when a caller (the test
suite) supplies one, otherwise from the app settings. Every model is imported via
``finance_app.db.registry`` so autogenerate sees the full schema.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from finance_app.core.config import get_settings
from finance_app.db import registry  # noqa: F401  (registers every model)
from finance_app.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> URL:
    url = config.attributes.get("database_url")
    return url if isinstance(url, URL) else get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (``alembic upgrade head --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect with the async driver and run migrations in a sync shim."""
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
