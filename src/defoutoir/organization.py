"""Build deterministic, side-effect-free media organization plans."""

from __future__ import annotations

import logging
import hashlib
import unicodedata
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from defoutoir.catalog import MediaRecord
from defoutoir.exif_dates import calculate_dated_sha1, supports_exif_date
from defoutoir.filename_dates import extract_filename_date
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
    exif_date: datetime | None = None
    source_sha1: str = ""


class OrganizationPlan(NamedTuple):
    """Complete deterministic organization plan and action counts."""

    output_directory: Path
    operation: PlanAction
    entries: tuple[OrganizationPlanEntry, ...]
    summary: dict[str, int]


def build_organization_plan(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    records: tuple[MediaRecord, ...] | list[MediaRecord],
    output_directory: str | Path,
    operation: str = "copy",
    logger: logging.Logger | None = None,
    date_unknown: bool = False,
    existing_content: Mapping[str, Path] | None = None,
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
    groups: dict[str, list[MediaRecord]] = {}
    for record in records:
        groups.setdefault(record.sha1, []).append(record)
    selected_groups = []
    for group in groups.values():
        representative = min(group, key=_canonical_record_key)
        selected_groups.append((representative, group))

    for representative, group in sorted(
        selected_groups, key=lambda item: item[0].source_path
    ):
        canonical = _plan_record(
            representative,
            output,
            requested_action,
            used_destinations,
            active_logger,
            date_unknown,
            existing_content,
        )
        entries.append(canonical)
        for duplicate in sorted(
            (record for record in group if record is not representative),
            key=lambda record: record.source_path,
        ):
            entries.append(
                OrganizationPlanEntry(
                    source_path=Path(duplicate.source_path),
                    destination_path=canonical.destination_path,
                    action=PlanAction.DUPLICATE,
                    reason="same source content is already represented in the plan",
                    sha1=canonical.sha1,
                    exif_date=None,
                    source_sha1=duplicate.sha1,
                )
            )

    summary = dict(Counter(entry.action.value for entry in entries))
    active_logger.info(
        "Organization plan complete: %d records; %s",
        len(entries),
        ", ".join(f"{key}={summary[key]}" for key in sorted(summary)),
    )
    return OrganizationPlan(output, requested_action, tuple(entries), summary)


def _plan_record(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    record: MediaRecord,
    output: Path,
    operation: PlanAction,
    used_destinations: dict[Path, str],
    logger: logging.Logger,
    date_unknown: bool,
    existing_content: Mapping[str, Path] | None,
) -> OrganizationPlanEntry:
    """Plan one record and reserve its deterministic destination."""
    source = Path(record.source_path)
    exif_date = _missing_exif_date(record, source, date_unknown, logger)
    relative_directory = _date_directory(record.media_date)
    normalized_name = unicodedata.normalize("NFC", source.name)
    destination = _safe_destination(output, relative_directory / normalized_name)
    if destination is None:
        return OrganizationPlanEntry(
            source,
            None,
            PlanAction.ERROR,
            "destination escapes output directory",
            record.sha1,
            exif_date,
            record.sha1,
        )

    try:
        output_sha1 = (
            calculate_dated_sha1(source, exif_date)
            if exif_date is not None
            and (destination.exists() or bool(existing_content))
            else record.sha1
        )
    except (OSError, ValueError) as error:
        logger.error("Cannot prepare EXIF update for %s: %s", source, error)
        return OrganizationPlanEntry(
            source,
            None,
            PlanAction.ERROR,
            f"cannot prepare EXIF update: {error}",
            record.sha1,
            exif_date,
            record.sha1,
        )

    existing_destination = (
        existing_content.get(output_sha1) if existing_content is not None else None
    )
    if existing_destination is not None:
        logger.info(
            "Planned duplicate: %s -> %s (content already exists in output)",
            source,
            existing_destination,
        )
        return OrganizationPlanEntry(
            source,
            existing_destination,
            PlanAction.DUPLICATE,
            "same content is already indexed in output",
            output_sha1,
            exif_date,
            record.sha1,
        )

    destination, reason = _resolve_collision(
        destination, output_sha1, used_destinations
    )
    used_destinations[destination] = output_sha1
    if destination.exists() or reason == "same content is planned at destination":
        action = PlanAction.DUPLICATE
        reason = "same content is already at destination"
    elif not source.is_file():
        action = PlanAction.ERROR
        reason = "source file is not readable"
    else:
        action = operation
    logger.info("Planned %s: %s -> %s", action.value, source, destination)
    return OrganizationPlanEntry(
        source,
        destination,
        action,
        reason,
        output_sha1,
        exif_date,
        record.sha1,
    )


def _canonical_record_key(record: MediaRecord) -> tuple[object, ...]:
    """Rank duplicate sources by date-bearing name, length, and stable path."""
    source = Path(record.source_path)
    normalized_name = unicodedata.normalize("NFC", source.name)
    contains_date = extract_filename_date(Path(normalized_name)) is not None
    return (
        not source.is_file(),
        not contains_date,
        len(normalized_name),
        normalized_name.casefold(),
        record.source_path.casefold(),
        record.source_path,
    )


def _missing_exif_date(
    record: MediaRecord,
    source: Path,
    enabled: bool,
    logger: logging.Logger,
) -> datetime | None:
    """Select a filename/path fallback date for supported undated images."""
    if not enabled or not record.media_date or not record.date_source:
        return None
    if not record.date_source.startswith(("filename.", "path.")):
        return None
    if not supports_exif_date(source):
        logger.warning(
            "Cannot add the detected date to unsupported EXIF format: %s", source
        )
        return None
    try:
        return datetime.fromisoformat(record.media_date)
    except ValueError:
        logger.warning("Cannot add invalid catalog date to EXIF: %s", record.media_date)
        return None


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
