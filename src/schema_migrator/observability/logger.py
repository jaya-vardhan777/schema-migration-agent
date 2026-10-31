"""structlog configuration — JSON in production, pretty console for dev."""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from schema_migrator.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Configure structlog + stdlib logging based on settings. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str = "schema_migrator") -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)
