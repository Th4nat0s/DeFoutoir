"""Command-line entry point for DeFoutoir."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from defoutoir import __version__
from defoutoir.catalog import CatalogError, MediaCatalog, MediaRecord
from defoutoir.executor import execute_organization_plan
from defoutoir.filename_dates import resolve_media_date
from defoutoir.log import configure_logging
from defoutoir.metadata import extract_media_date
from defoutoir.organization import build_organization_plan
from defoutoir.scanner import discover_media

EXIT_SUCCESS = 0
EXIT_PROCESSING_ERROR = 1
EXIT_VALIDATION_ERROR = 2


class CLIValidationError(ValueError):
    """Raise when command-line options cannot describe a safe operation."""


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="defoutoir",
        description="Clean and sort pictures and movies by date.",
        epilog=(
            "Examples: defoutoir --input ./media --output ./sorted; "
            "defoutoir --input ./media --learn"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--input",
        dest="input_directories",
        action="append",
        required=True,
        metavar="DIRECTORY",
        help="input directory; repeat for multiple directories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="DIRECTORY",
        help="destination directory for organization operations",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("defoutoir.sqlite3"),
        metavar="PATH",
        help="SQLite catalog path (default: defoutoir.sqlite3)",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="move files instead of copying them",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and display the plan without changing files",
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="catalog media and dates without organizing files",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show detailed status messages",
    )
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="show warnings and errors only",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the complete DeFoutoir workflow and return a stable exit code."""
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
        _validate_arguments(arguments)
    except CLIValidationError as error:
        logger = configure_logging(logging.ERROR)
        logger.error("%s", error)
        return EXIT_VALIDATION_ERROR

    level = (
        logging.WARNING
        if arguments.quiet
        else logging.DEBUG if arguments.verbose else logging.INFO
    )
    logger = configure_logging(level)
    logger.info("Starting DeFoutoir.")

    try:
        discovery = discover_media(arguments.input_directories, logger)
        with MediaCatalog(arguments.database, logger) as catalog:
            records, catalog_errors = _catalog_media(
                discovery.media_files, catalog, logger
            )
            if arguments.learn:
                logger.info("Learn complete: %d media files cataloged.", len(records))
                return EXIT_PROCESSING_ERROR if catalog_errors else EXIT_SUCCESS

            operation = "move" if arguments.move else "copy"
            plan = build_organization_plan(records, arguments.output, operation, logger)
            if arguments.dry_run:
                logger.info("Dry run complete: %s", _format_summary(plan.summary))
                return EXIT_PROCESSING_ERROR if catalog_errors else EXIT_SUCCESS

            result = execute_organization_plan(plan, catalog, logger)
            if result.summary.get("error", 0) or catalog_errors:
                logger.error(
                    "Processing completed with errors: %s",
                    _format_summary(result.summary),
                )
                return EXIT_PROCESSING_ERROR
            logger.info("Processing complete: %s", _format_summary(result.summary))
            return EXIT_SUCCESS
    except (CatalogError, OSError, RuntimeError) as error:
        logger.error("Processing failed: %s", error)
        return EXIT_PROCESSING_ERROR


def _validate_arguments(arguments: argparse.Namespace) -> None:
    """Validate paths and incompatible modes before opening the catalog."""
    input_paths = tuple(
        Path(value).expanduser() for value in arguments.input_directories
    )
    resolved_inputs: list[Path] = []
    for input_path in input_paths:
        try:
            resolved = input_path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise CLIValidationError(
                f"Input directory does not exist or cannot be read: {input_path}"
            ) from error
        if not resolved.is_dir():
            raise CLIValidationError(f"Input path is not a directory: {input_path}")
        resolved_inputs.append(resolved)

    if arguments.learn and arguments.move:
        raise CLIValidationError("--move cannot be combined with --learn")
    if arguments.learn and arguments.dry_run:
        raise CLIValidationError("--dry-run cannot be combined with --learn")
    if not arguments.learn and arguments.output is None:
        raise CLIValidationError("--output is required unless --learn is used")
    if arguments.output is None:
        return

    output = arguments.output.expanduser().resolve(strict=False)
    if output.exists() and not output.is_dir():
        raise CLIValidationError(f"Output path is not a directory: {arguments.output}")
    for input_path in resolved_inputs:
        if (
            output == input_path
            or output.is_relative_to(input_path)
            or input_path.is_relative_to(output)
        ):
            raise CLIValidationError(
                "Input and output directories must not overlap; "
                "choose a separate output directory"
            )


def _catalog_media(
    media_files: tuple[Path, ...],
    catalog: MediaCatalog,
    logger: logging.Logger,
) -> tuple[tuple[MediaRecord, ...], int]:
    """Extract dates and upsert discovered files into the catalog."""
    records: list[MediaRecord] = []
    error_count = 0
    for media_path in media_files:
        metadata_date = extract_media_date(media_path, logger)
        resolved_date = resolve_media_date(media_path, metadata_date, logger)
        media_date = resolved_date.value.isoformat(sep=" ") if resolved_date else None
        date_source = resolved_date.source if resolved_date else None
        try:
            records.append(
                catalog.record_file(
                    media_path,
                    media_date=media_date,
                    date_source=date_source,
                )
            )
        except CatalogError as error:
            logger.error("Could not catalog %s: %s", media_path, error)
            error_count += 1
    logger.info(
        "Cataloged %d of %d discovered media files.", len(records), len(media_files)
    )
    return tuple(records), error_count


def _format_summary(summary: dict[str, int]) -> str:
    """Format action counts in deterministic order."""
    return ", ".join(f"{key}={summary[key]}" for key in sorted(summary)) or "none"
