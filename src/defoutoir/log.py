"""Shared logging configuration for DeFoutoir."""

from __future__ import annotations

import logging
import sys
from typing import TextIO

LOGGER_NAME = "defoutoir"
LOG_FORMAT = "%(levelname)s: %(message)s"


def configure_logging(
    level: int = logging.INFO,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure and return the shared application logger."""
    logger = logging.getLogger(LOGGER_NAME)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(module_name: str) -> logging.Logger:
    """Return a child logger for an application module."""
    return logging.getLogger(f"{LOGGER_NAME}.{module_name}")
