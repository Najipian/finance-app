"""Application factory.

Run with ``uvicorn finance_app.main:create_app --factory``. There is deliberately
no module-level ``app``: importing this module has no side effects, and tests build
an app with their own settings.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from finance_app import __version__
from finance_app.api.router import api_router
from finance_app.core.config import Settings, get_settings
from finance_app.core.errors import register_exception_handlers
from finance_app.core.logging import configure_logging
from finance_app.core.rate_limit import RateLimiter
from finance_app.db.session import create_engine, create_sessionmaker

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open shared clients (DB engine, Redis) at startup and close them at shutdown.

    Args:
        app: The application; clients are stored on ``app.state``.

    Yields:
        Control to the running application.
    """
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    redis: Redis = Redis.from_url(settings.redis_url)
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis
    app.state.rate_limiter = RateLimiter(redis, enabled=settings.rate_limit_enabled)
    log.info("startup", environment=settings.environment.value, version=__version__)
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Settings to use; defaults to the environment via ``get_settings``.

    Returns:
        A configured ``FastAPI`` instance.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Personal finance on UK/EU Open Banking (read-only AIS).",
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    register_exception_handlers(app)
    app.include_router(api_router)
    return app
