"""Command-line entry point for DeFoutoir."""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from defoutoir import __version__
from defoutoir.catalog import (
    CatalogError,
    MediaCatalog,
    MediaRecord,
    read_catalog_records,
)
from defoutoir.executor import execute_organization_plan
from defoutoir.learning import learn_media
from defoutoir.log import configure_logging
from defoutoir.organization import OrganizationPlan, build_organization_plan
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
            "Examples: python defoutoir.py --input ./media --output ./sorted; "
            "python defoutoir.py --input ./media --learn"
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
    list_modes = parser.add_mutually_exclusive_group()
    list_modes.add_argument(
        "--list",
        dest="list_mode",
        action="store_const",
        const="all",
        help="list all catalog records",
    )
    list_modes.add_argument(
        "--list-no-date",
        dest="list_mode",
        action="store_const",
        const="no-date",
        help="list records without a resolved date",
    )
    list_modes.add_argument(
        "--list-errors",
        dest="list_mode",
        action="store_const",
        const="errors",
        help="list records in error state",
    )
    list_modes.add_argument(
        "--list-duplicates",
        dest="list_mode",
        action="store_const",
        const="duplicates",
        help="list records whose SHA-1 is shared by multiple files",
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


def main(  # pylint: disable=too-many-return-statements
    argv: Sequence[str] | None = None,
) -> int:
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
        if arguments.list_mode:
            records = read_catalog_records(arguments.database)
            records = _filter_catalog_records(records, arguments.list_mode)
            _print_catalog_records(records)
            logger.info("Listed %d catalog records.", len(records))
            return EXIT_SUCCESS

        discovery = discover_media(arguments.input_directories, logger)
        database_path = ":memory:" if arguments.dry_run else arguments.database
        with MediaCatalog(database_path, logger) as catalog:
            learning = learn_media(
                discovery.media_files,
                tuple(arguments.input_directories),
                catalog,
                logger,
                discovery.warning_count,
            )
            records = learning.records
            catalog_errors = learning.summary.get("error", 0)
            if arguments.learn:
                logger.info("Learn summary: %s", _format_summary(learning.summary))
                return EXIT_PROCESSING_ERROR if catalog_errors else EXIT_SUCCESS

            operation = "move" if arguments.move else "copy"
            plan = build_organization_plan(records, arguments.output, operation, logger)
            if arguments.dry_run:
                _log_dry_run_plan(plan, logger)
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


def _validate_arguments(  # pylint: disable=too-many-branches
    arguments: argparse.Namespace,
) -> None:
    """Validate paths and incompatible modes before opening the catalog."""
    if arguments.list_mode:
        if arguments.input_directories:
            raise CLIValidationError("a list option cannot be combined with --input")
        if arguments.output or arguments.move or arguments.dry_run or arguments.learn:
            raise CLIValidationError(
                "a list option cannot be combined with --output, --move, "
                "--dry-run, or --learn"
            )
        if not arguments.database.is_file():
            raise CLIValidationError(
                f"Catalog database does not exist: {arguments.database}"
            )
        return

    if not arguments.input_directories:
        raise CLIValidationError("--input is required unless --list is used")
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


def _format_summary(summary: dict[str, int]) -> str:
    """Format action counts in deterministic order."""
    return ", ".join(f"{key}={summary[key]}" for key in sorted(summary)) or "none"


def _print_catalog_records(records: tuple[MediaRecord, ...]) -> None:
    """Print catalog records as stable tab-separated output."""
    print("timestamp\tdate_source\tname\tsha1\tpathname")
    for record in records:
        print(
            f"{record.media_date or '-'}\t{record.date_source or '-'}\t"
            f"{Path(record.source_path).name}\t{record.sha1}\t{record.source_path}"
        )


def _filter_catalog_records(
    records: tuple[MediaRecord, ...], list_mode: str
) -> tuple[MediaRecord, ...]:
    """Select catalog records for a read-only list mode."""
    if list_mode == "no-date":
        return tuple(record for record in records if record.media_date is None)
    if list_mode == "errors":
        return tuple(record for record in records if record.processing_state == "error")
    if list_mode == "duplicates":
        counts = Counter(record.sha1 for record in records)
        duplicates = (record for record in records if counts[record.sha1] > 1)
        return tuple(
            sorted(duplicates, key=lambda record: (record.sha1, record.source_path))
        )
    return records


def _log_dry_run_plan(plan: OrganizationPlan, logger: logging.Logger) -> None:
    """Report every preview action and its expected destination."""
    for entry in plan.entries:
        destination = entry.destination_path or "<none>"
        logger.info(
            "DRY-RUN %s: %s -> %s (%s)",
            entry.action.value,
            entry.source_path,
            destination,
            entry.reason,
        )
