"""Structured logging utility — eliminates boilerplate across domain services."""

from __future__ import annotations

import logging
from typing import Any


def structured_log(
    logger: logging.Logger,
    level: str,
    event: str,
    /,
    **fields: Any,
) -> None:
    """Emit a structured log entry.

    The event name is passed as the log message. The JsonLogFormatter in
    logging_config.py extracts it via record.getMessage() when no explicit
    'event' key exists in extra — so we do NOT duplicate it.

    Usage:
        structured_log(logger, "info", "ingestion.run_started", user_id=1, scholar_count=5)
    """
    fields.pop("metric_name", None)
    fields.pop("metric_value", None)

    log_method = getattr(logger, level.lower())
    log_method(event, extra=fields)
