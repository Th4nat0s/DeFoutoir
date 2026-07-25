"""Command-line entry point for DeFoutoir."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from defoutoir import __version__
from defoutoir.log import configure_logging


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="defoutoir",
        description="Clean and sort pictures and movies by date.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show detailed status messages",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line application."""
    arguments = build_parser().parse_args(argv)
    level = logging.DEBUG if arguments.verbose else logging.INFO
    logger = configure_logging(level)
    logger.info("DeFoutoir is ready.")
    return 0
