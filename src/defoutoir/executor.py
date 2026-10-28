"""Execute organization plans with exclusive, recoverable file operations."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from defoutoir.catalog import CatalogError, MediaCatalog, calculate_sha1
from defoutoir.exif_dates import write_missing_exif_date
from defoutoir.log import get_logger
from defoutoir.organization import OrganizationPlan, OrganizationPlanEntry, PlanAction


class ExecutionEntry(NamedTuple):
    """Result of executing one planned entry."""

    plan_entry: OrganizationPlanEntry
    success: bool
    error: str | None


class ExecutionResult(NamedTuple):
    """Complete execution result and action summary."""

    entries: tuple[ExecutionEntry, ...]
    summary: dict[str, int]


def execute_organization_plan(
    plan: OrganizationPlan,
    catalog: MediaCatalog | None = None,
    logger: logging.Logger | None = None,
) -> ExecutionResult:
    """Execute each safe plan entry and continue after per-file failures."""
    active_logger = logger or get_logger("executor")
    _prepare_journal(plan, catalog)
    results: list[ExecutionEntry] = []
    for plan_entry in plan.entries:
        result = _execute_entry(
            plan_entry,
            plan.operation,
            plan.output_directory,
            catalog,
            active_logger,
        )
        results.append(result)

    summary = dict(Counter(_result_key(result) for result in results))
    active_logger.info(
        "Execution complete: %d entries; %s",
        len(results),
        ", ".join(f"{key}={summary[key]}" for key in sorted(summary)),
    )
    return ExecutionResult(tuple(results), summary)


def _execute_entry(
    plan_entry: OrganizationPlanEntry,
    operation: PlanAction,
    output_directory: Path,
    catalog: MediaCatalog | None,
    logger: logging.Logger,
) -> ExecutionEntry:
    """Execute one entry and convert operational failures into a result."""
    if plan_entry.action is PlanAction.ERROR:
        _record_state(catalog, plan_entry.source_path, "error", logger)
        return ExecutionEntry(plan_entry, False, plan_entry.reason)
    if plan_entry.action is PlanAction.DUPLICATE:
        resumed = _resume_published_operation(
            plan_entry, operation, output_directory, catalog, logger
        )
        if resumed is not None:
            return resumed
    if plan_entry.action in (PlanAction.SKIP, PlanAction.DUPLICATE):
        state = "duplicate" if plan_entry.action is PlanAction.DUPLICATE else "skipped"
        _record_state(catalog, plan_entry.source_path, state, logger)
        logger.info("Skipping %s: %s", plan_entry.source_path, plan_entry.reason)
        return ExecutionEntry(plan_entry, True, None)
    if plan_entry.destination_path is None:
        error = "planned destination is missing"
        _record_state(catalog, plan_entry.source_path, "error", logger)
        return ExecutionEntry(plan_entry, False, error)

    try:
        if plan_entry.action is PlanAction.COPY:
            _copy_plan_entry(plan_entry, logger)
            _record_output(plan_entry, output_directory, catalog)
            _checkpoint(plan_entry, operation, catalog, "copied")
        elif plan_entry.action is PlanAction.MOVE:
            _copy_plan_entry(plan_entry, logger)
            _record_output(plan_entry, output_directory, catalog)
            _checkpoint(plan_entry, operation, catalog, "copied")
            if not _source_matches_entry(plan_entry, catalog):
                raise ValueError("source changed while the move was being published")
            plan_entry.source_path.unlink()
        else:
            raise ValueError(f"unsupported plan action: {plan_entry.action}")
    except (CatalogError, OSError, shutil.Error, ValueError) as error:
        logger.error(
            "Could not execute %s: %s -> %s: %s",
            plan_entry.action.value,
            plan_entry.source_path,
            plan_entry.destination_path,
            error,
        )
        _checkpoint(plan_entry, operation, catalog, "error", str(error), logger)
        _record_state(catalog, plan_entry.source_path, "error", logger)
        return ExecutionEntry(plan_entry, False, str(error))

    state = "copied" if plan_entry.action is PlanAction.COPY else "moved"
    _checkpoint(plan_entry, operation, catalog, "completed")
    _record_state(catalog, plan_entry.source_path, state, logger)
    logger.info(
        "Executed %s: %s -> %s",
        plan_entry.action.value,
        plan_entry.source_path,
        plan_entry.destination_path,
    )
    return ExecutionEntry(plan_entry, True, None)


def _prepare_journal(
    plan: OrganizationPlan,
    catalog: MediaCatalog | None,
) -> None:
    """Durably record every transfer before the first file is changed."""
    if catalog is None:
        return
    for entry in plan.entries:
        journal_duplicate_move = (
            plan.operation is PlanAction.MOVE and entry.action is PlanAction.DUPLICATE
        )
        if (
            entry.action not in (PlanAction.COPY, PlanAction.MOVE)
            and not journal_duplicate_move
        ):
            continue
        if entry.destination_path is None:
            continue
        existing = catalog.get_operation(
            entry.source_path,
            entry.destination_path,
            plan.operation.value,
            entry.sha1,
        )
        if (
            entry.action is PlanAction.DUPLICATE
            and existing is not None
            and existing.status == "completed"
            and not entry.source_path.exists()
        ):
            continue
        catalog.prepare_operation(
            entry.source_path,
            entry.destination_path,
            plan.operation.value,
            entry.sha1,
        )


def _resume_published_operation(
    entry: OrganizationPlanEntry,
    operation: PlanAction,
    output_directory: Path,
    catalog: MediaCatalog | None,
    logger: logging.Logger,
) -> ExecutionEntry | None:
    """Finish an interrupted operation whose destination is already present."""
    if catalog is None or entry.destination_path is None:
        return None
    journal = catalog.get_operation(
        entry.source_path,
        entry.destination_path,
        operation.value,
        entry.sha1,
    )
    if journal is None or journal.status == "completed":
        return None
    try:
        if calculate_sha1(entry.destination_path) != entry.sha1:
            raise ValueError("published destination does not match the journal hash")
        if operation is PlanAction.MOVE and entry.source_path.exists():
            if not _source_matches_entry(entry, catalog):
                raise ValueError("source changed after it was cataloged")
            entry.source_path.unlink()
        catalog.record_output_content(
            output_directory,
            entry.destination_path,
            entry.source_sha1 or entry.sha1,
            entry.sha1,
        )
        catalog.update_operation(
            entry.source_path,
            entry.destination_path,
            operation.value,
            entry.sha1,
            "completed",
        )
    except (CatalogError, OSError, ValueError) as error:
        logger.error(
            "Could not resume %s: %s -> %s: %s",
            operation.value,
            entry.source_path,
            entry.destination_path,
            error,
        )
        _checkpoint(entry, operation, catalog, "error", str(error), logger)
        _record_state(catalog, entry.source_path, "error", logger)
        return ExecutionEntry(entry, False, str(error))

    resumed_entry = entry._replace(
        action=operation,
        reason="resumed from operation journal",
    )
    state = "copied" if operation is PlanAction.COPY else "moved"
    _record_state(catalog, entry.source_path, state, logger)
    logger.info(
        "Resumed %s: %s -> %s",
        operation.value,
        entry.source_path,
        entry.destination_path,
    )
    return ExecutionEntry(resumed_entry, True, None)


def _record_output(
    entry: OrganizationPlanEntry,
    output_directory: Path,
    catalog: MediaCatalog | None,
) -> None:
    """Add one published file to its output-specific content index."""
    if catalog is None or entry.destination_path is None:
        return
    catalog.record_output_content(
        output_directory,
        entry.destination_path,
        entry.source_sha1 or entry.sha1,
        entry.sha1,
    )


def _source_matches_entry(
    entry: OrganizationPlanEntry,
    catalog: MediaCatalog | None,
) -> bool:
    """Verify cheaply that a source still has its cataloged content identity."""
    expected_sha1 = entry.source_sha1 or entry.sha1
    if catalog is not None:
        record = catalog.get_by_path(entry.source_path)
        try:
            details = entry.source_path.stat()
        except OSError:
            return False
        if (
            record is not None
            and record.sha1 == expected_sha1
            and record.size_bytes == details.st_size
            and record.modified_ns == details.st_mtime_ns
            and record.metadata_changed_ns == details.st_ctime_ns
        ):
            return True
    try:
        return calculate_sha1(entry.source_path) == expected_sha1
    except CatalogError:
        return False


def _checkpoint(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    entry: OrganizationPlanEntry,
    operation: PlanAction,
    catalog: MediaCatalog | None,
    status: str,
    error: str | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Persist one execution checkpoint when a catalog is available."""
    if catalog is None or entry.destination_path is None:
        return
    try:
        catalog.update_operation(
            entry.source_path,
            entry.destination_path,
            operation.value,
            entry.sha1,
            status,
            error,
        )
    except CatalogError as journal_error:
        if logger is None:
            raise
        logger.error(
            "Could not record journal checkpoint %s for %s: %s",
            status,
            entry.source_path,
            journal_error,
        )


def _copy_plan_entry(plan_entry: OrganizationPlanEntry, logger: logging.Logger) -> None:
    """Copy one entry and apply its optional EXIF update before publication."""
    if plan_entry.destination_path is None:
        raise ValueError("planned destination is missing")
    if plan_entry.exif_date is None:
        _copy_exclusive(plan_entry.source_path, plan_entry.destination_path)
        return
    _copy_exclusive(
        plan_entry.source_path,
        plan_entry.destination_path,
        plan_entry.exif_date,
        logger,
    )


def _copy_exclusive(
    source: Path,
    destination: Path,
    exif_date: datetime | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Copy with metadata while guaranteeing that an existing file stays intact."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.stem}.",
            suffix=destination.suffix,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with source.open("rb") as source_stream:
                shutil.copyfileobj(source_stream, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        shutil.copystat(source, temporary_path)
        if exif_date is not None:
            write_missing_exif_date(temporary_path, exif_date, logger)
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _record_state(
    catalog: MediaCatalog | None,
    source: Path,
    state: str,
    logger: logging.Logger,
) -> None:
    """Update the catalog when one was supplied, without hiding file results."""
    if catalog is None:
        return
    try:
        catalog.update_processing_state(source, state)
    except CatalogError as error:
        logger.error("Could not record %s for %s: %s", state, source, error)


def _result_key(result: ExecutionEntry) -> str:
    """Return a stable summary key for one execution result."""
    if result.success:
        return result.plan_entry.action.value
    return "error"
