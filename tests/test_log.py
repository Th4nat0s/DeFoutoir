"""Tests for shared logging configuration."""

from __future__ import annotations

import logging
import sys

from defoutoir.log import LOGGER_NAME, configure_logging, get_logger


def test_logging_configuration_is_reusable(capsys) -> None:
    """Repeated configuration must not duplicate log messages."""
    logger = configure_logging(logging.INFO, stream=sys.stderr)
    configure_logging(logging.INFO, stream=sys.stderr)

    logger.info("Scanning test media.")

    captured = capsys.readouterr()
    assert captured.err == "INFO: Scanning test media.\n"
    assert len(logger.handlers) == 1


def test_child_logger_uses_application_namespace() -> None:
    """Modules must receive loggers under the shared namespace."""
    logger = get_logger("scanner")

    assert logger.name == f"{LOGGER_NAME}.scanner"
