"""Structured logging with structlog.

Local and test runs get readable console output; production gets one JSON object
per line so CloudWatch can search it. Never log tokens, passwords, full IBANs or
raw provider payloads.
"""

import logging

import structlog

from finance_app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog (and the stdlib root logger) for this process.

    Args:
        settings: Application settings; uses ``log_level`` and ``environment``.
    """
    level = logging.getLevelNamesMapping()[settings.log_level]
    logging.basicConfig(level=level, format="%(message)s")

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
