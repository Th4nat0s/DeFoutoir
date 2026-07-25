"""Build deterministic, side-effect-free media organization plans."""

from __future__ import annotations

import logging
import hashlib
from collections import Counter
from datetime import date
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from defoutoir.catalog import MediaRecord
from defoutoir.log import get_logger


class PlanAction(str, Enum):
    """Action that a later executor may apply to one media record."""

    COPY = "copy"
    MOVE = "move"
    SKIP = "skip"
    DUPLICATE = "duplicate"
    ERROR = "error"


class OrganizationPlanEntry(NamedTuple):
    """One planned source-to-destination operation."""

    source_path: Path
    destination_path: Path | None
    action: PlanAction
    reason: str
    sha1: str


class OrganizationPlan(NamedTuple):
    """Complete deterministic organization plan and action counts."""

    output_directory: Path
    operation: PlanAction
    entries: tuple[OrganizationPlanEntry, ...]
    summary: dict[str, int]


def build_organization_plan(
    records: tuple[MediaRecord, ...] | list[MediaRecord],
    output_directory: str | Path,
    operation: str = "copy",
    logger: logging.Logger | None = None,
) -> OrganizationPlan:
    """Build a plan without creating directories or changing any files."""
    active_logger = logger or get_logger("organization")
    try:
        requested_action = PlanAction(operation)
    except ValueError as error:
        raise ValueError("operation must be 'copy' or 'move'") from error
    if requested_action not in (PlanAction.COPY, PlanAction.MOVE):
        raise ValueError("operation must be 'copy' or 'move'")

    output = Path(output_directory).expanduser().resolve(strict=False)
    entries: list[OrganizationPlanEntry] = []
    used_destinations: dict[Path, str] = {}
    for record in sorted(records, key=lambda item: item.source_path):
        entry = _plan_record(
            record,
            output,
            requested_action,
            used_destinations,
            active_logger,
        )
        entries.append(entry)

    summary = dict(Counter(entry.action.value for entry in entries))
    active_logger.info(
        "Organization plan complete: %d records; %s",
        len(entries),
        ", ".join(f"{key}={summary[key]}" for key in sorted(summary)),
    )
    return OrganizationPlan(output, requested_action, tuple(entries), summary)


def _plan_record(
    record: MediaRecord,
    output: Path,
    operation: PlanAction,
    used_destinations: dict[Path, str],
    logger: logging.Logger,
) -> OrganizationPlanEntry:
    """Plan one record and reserve its deterministic destination."""
    source = Path(record.source_path)
    if not source.is_file():
        return OrganizationPlanEntry(
            source, None, PlanAction.ERROR, "source file is not readable", record.sha1
        )

    relative_directory = _date_directory(record.media_date)
    destination = _safe_destination(output, relative_directory / source.name)
    if destination is None:
        return OrganizationPlanEntry(
            source,
            None,
            PlanAction.ERROR,
            "destination escapes output directory",
            record.sha1,
        )

    destination, reason = _resolve_collision(
        destination, record.sha1, used_destinations
    )
    used_destinations[destination] = record.sha1
    if destination.exists() or reason == "same content is planned at destination":
        action = PlanAction.DUPLICATE
        reason = "same content is already at destination"
    else:
        action = operation
    logger.info("Planned %s: %s -> %s", action.value, source, destination)
    return OrganizationPlanEntry(source, destination, action, reason, record.sha1)


def _date_directory(media_date: str | None) -> Path:
    """Return the canonical relative directory for a catalog date."""
    if not media_date:
        return Path("unknown")
    try:
        captured = date.fromisoformat(media_date[:10])
    except ValueError:
        return Path("unknown")
    return (
        Path(f"{captured.year:04d}") / f"{captured.month:02d}" / f"{captured.day:02d}"
    )


def _safe_destination(output: Path, relative_path: Path) -> Path | None:
    """Resolve a candidate and reject paths outside the output directory."""
    candidate = (output / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(output)
    except ValueError:
        return None
    return candidate


def _resolve_collision(
    destination: Path,
    sha1: str,
    used_destinations: dict[Path, str],
) -> tuple[Path, str]:
    """Choose a stable alternate name when a different file collides."""
    known_hash = used_destinations.get(destination)
    if known_hash is not None:
        if known_hash == sha1:
            return destination, "same content is planned at destination"
        return _alternate_destination(destination, sha1, used_destinations)
    if not destination.exists():
        return destination, "destination is available"
    if destination.is_file() and _sha1(destination) == sha1:
        return destination, "same content is already at destination"
    return _alternate_destination(destination, sha1, used_destinations)


def _alternate_destination(
    destination: Path,
    sha1: str,
    used_destinations: dict[Path, str],
) -> tuple[Path, str]:
    """Generate a deterministic collision-safe destination name."""
    stem = destination.stem
    suffix = destination.suffix
    for length in (8, 12, 16, 40):
        candidate = destination.with_name(f"{stem}__{sha1[:length]}{suffix}")
        if candidate not in used_destinations and not candidate.exists():
            return candidate, "different content uses a deterministic alternate name"
    counter = 2
    while True:
        candidate = destination.with_name(f"{stem}__{sha1}_{counter}{suffix}")
        if candidate not in used_destinations and not candidate.exists():
            return candidate, "different content uses a deterministic alternate name"
        counter += 1


def _sha1(path: Path) -> str | None:
    """Hash an existing destination without changing it."""
    digest = hashlib.sha1(usedforsecurity=False)
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
