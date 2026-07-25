"""Execute organization plans with exclusive, recoverable file operations."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from defoutoir.catalog import CatalogError, MediaCatalog
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
    results: list[ExecutionEntry] = []
    for plan_entry in plan.entries:
        result = _execute_entry(plan_entry, catalog, active_logger)
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
    catalog: MediaCatalog | None,
    logger: logging.Logger,
) -> ExecutionEntry:
    """Execute one entry and convert operational failures into a result."""
    if plan_entry.action is PlanAction.ERROR:
        _record_state(catalog, plan_entry.source_path, "error", logger)
        return ExecutionEntry(plan_entry, False, plan_entry.reason)
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
            _copy_exclusive(plan_entry.source_path, plan_entry.destination_path)
        elif plan_entry.action is PlanAction.MOVE:
            _copy_exclusive(plan_entry.source_path, plan_entry.destination_path)
            plan_entry.source_path.unlink()
        else:
            raise ValueError(f"unsupported plan action: {plan_entry.action}")
    except (OSError, shutil.Error, ValueError) as error:
        logger.error(
            "Could not execute %s: %s -> %s: %s",
            plan_entry.action.value,
            plan_entry.source_path,
            plan_entry.destination_path,
            error,
        )
        _record_state(catalog, plan_entry.source_path, "error", logger)
        return ExecutionEntry(plan_entry, False, str(error))

    state = "copied" if plan_entry.action is PlanAction.COPY else "moved"
    _record_state(catalog, plan_entry.source_path, state, logger)
    logger.info(
        "Executed %s: %s -> %s",
        plan_entry.action.value,
        plan_entry.source_path,
        plan_entry.destination_path,
    )
    return ExecutionEntry(plan_entry, True, None)


def _copy_exclusive(source: Path, destination: Path) -> None:
    """Copy with metadata while guaranteeing that an existing file stays intact."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            with source.open("rb") as source_stream:
                shutil.copyfileobj(source_stream, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        shutil.copystat(source, temporary_path)
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
