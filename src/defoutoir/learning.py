"""Catalog-only media learning and state classification."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from defoutoir.catalog import CatalogError, MediaCatalog, MediaRecord
from defoutoir.filename_dates import resolve_media_date
from defoutoir.log import get_logger
from defoutoir.metadata import extract_media_date


class LearnResult(NamedTuple):
    """Catalog records and deterministic learning summary."""

    records: tuple[MediaRecord, ...]
    summary: dict[str, int]


def learn_media(
    media_files: tuple[Path, ...],
    input_directories: tuple[str | Path, ...],
    catalog: MediaCatalog,
    logger: logging.Logger | None = None,
    discovery_warnings: int = 0,
) -> LearnResult:
    """Hash, date, classify, and persist media without file operations."""
    active_logger = logger or get_logger("learning")
    records: list[MediaRecord] = []
    statuses: list[str] = []
    for media_path in media_files:
        record, status = _learn_one(media_path, catalog, active_logger)
        if record is not None:
            records.append(record)
        statuses.append(status)

    discovered_paths = {
        str(media_path.expanduser().resolve(strict=False)) for media_path in media_files
    }
    missing_count = _mark_missing(
        input_directories,
        discovered_paths,
        catalog,
        active_logger,
    )
    statuses.extend("missing" for _ in range(missing_count))
    if discovery_warnings:
        statuses.extend("warning" for _ in range(discovery_warnings))

    summary = dict(Counter(statuses))
    active_logger.info("Learn complete: %s", _format_summary(summary))
    return LearnResult(tuple(records), summary)


def _learn_one(
    media_path: Path,
    catalog: MediaCatalog,
    logger: logging.Logger,
) -> tuple[MediaRecord | None, str]:
    """Learn and classify one media file."""
    existing = catalog.get_by_path(media_path)
    metadata_date = extract_media_date(media_path, logger)
    resolved_date = resolve_media_date(media_path, metadata_date, logger)
    media_date = resolved_date.value.isoformat(sep=" ") if resolved_date else None
    date_source = resolved_date.source if resolved_date else None
    try:
        record = catalog.record_file(
            media_path,
            media_date=media_date,
            date_source=date_source,
        )
    except CatalogError as error:
        logger.error("Could not learn %s: %s", media_path, error)
        return None, "error"

    status = _classify_record(existing, record, catalog)
    try:
        record = catalog.update_processing_state(record.source_path, status)
    except CatalogError as error:
        logger.error("Could not record %s for %s: %s", status, media_path, error)
        return None, "error"
    logger.info("Learned %s: %s", status, media_path)
    return record, status


def _classify_record(
    existing: MediaRecord | None,
    record: MediaRecord,
    catalog: MediaCatalog,
) -> str:
    """Classify a record by prior identity and duplicate content."""
    if existing is None:
        status = "learned"
    elif existing.sha1 == record.sha1:
        status = "unchanged"
    else:
        status = "updated"
    duplicates = tuple(
        item
        for item in catalog.find_by_sha1(record.sha1)
        if item.source_path != record.source_path
    )
    return "duplicate" if duplicates else status


def _mark_missing(
    input_directories: tuple[str | Path, ...],
    discovered_paths: set[str],
    catalog: MediaCatalog,
    logger: logging.Logger,
) -> int:
    """Mark previously learned files absent from the current input trees."""
    roots = tuple(
        Path(directory).expanduser().resolve(strict=False)
        for directory in input_directories
    )
    missing_count = 0
    for record in catalog.all_records():
        source = Path(record.source_path)
        if record.source_path in discovered_paths:
            continue
        if not any(source.is_relative_to(root) for root in roots):
            continue
        try:
            catalog.update_processing_state(source, "missing")
        except CatalogError as error:
            logger.error("Could not mark missing media %s: %s", source, error)
            continue
        missing_count += 1
        logger.warning("Previously learned media is missing: %s", source)
    return missing_count


def _format_summary(summary: dict[str, int]) -> str:
    """Format learning counts in deterministic order."""
    return ", ".join(f"{key}={summary[key]}" for key in sorted(summary)) or "none"
