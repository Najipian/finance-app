"""arq worker configuration.

Run with ``arq finance_app.worker.settings.WorkerSettings``. Real jobs
(``sync_connection``, ``check_consent_expiry``, ...) arrive in Week 3; ``ping``
exists so the worker has a job to register and can be smoke-tested.
"""

from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings

from finance_app.core.config import get_settings
from finance_app.core.logging import configure_logging

log = structlog.get_logger(__name__)


async def ping(ctx: dict[str, Any]) -> str:
    """Trivial job used to check that the worker consumes the queue.

    Args:
        ctx: arq job context.

    Returns:
        The string ``"pong"``.
    """
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    """Configure logging when the worker process starts.

    Args:
        ctx: arq worker context.
    """
    configure_logging(get_settings())
    log.info("worker_startup")


class WorkerSettings:
    """Settings object that the ``arq`` CLI reads."""

    functions: ClassVar[list[Any]] = [ping]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
