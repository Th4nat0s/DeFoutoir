"""Extract explicit capture dates from media filenames."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import NamedTuple

from defoutoir.metadata import MetadataDate


class FilenameDate(NamedTuple):
    """A valid date found in a filename."""

    value: date
    source: str
    pattern: str
    raw_value: str
    capture_time: time | None = None


class ResolvedDate(NamedTuple):
    """The date selected from metadata or a filename fallback."""

    value: datetime
    source: str
    raw_value: str
    pattern: str | None


_DATE_PATTERNS = (
    (
        "compact_yyyymmdd",
        re.compile(r"(?<!\d)(?P<year>\d{4})(?P<month>\d{2})" + r"(?P<day>\d{2})(?!\d)"),
    ),
    (
        "separated_yyyy_mm_dd",
        re.compile(
            r"(?<!\d)(?P<year>\d{4})(?P<separator>[-_.])"
            r"(?P<month>\d{2})(?P=separator)(?P<day>\d{2})(?!\d)"
        ),
    ),
)
_PATH_YEAR = re.compile(r"^(?P<year>\d{4})$")
_PATH_MONTH_DAY = re.compile(r"^(?P<month>\d{2})(?P<day>\d{2})(?:$|[\s_-])")
_FILENAME_TIME = re.compile(
    r"^(?:\s+at\s+|[_ -]+)(?P<hour>\d{2})[.:]"
    r"(?P<minute>\d{2})[.:](?P<second>\d{2})(?!\d)"
)
_COMPACT_FILENAME_TIME = re.compile(
    r"^(?:[_ -]+)(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})(?!\d)"
)


def _extract_filename_time(
    suffix: str, filename: str, logger: logging.Logger
) -> tuple[time | None, str]:
    """Extract an optional HHMMSS or HH.MM.SS suffix from a filename."""
    match = _FILENAME_TIME.match(suffix) or _COMPACT_FILENAME_TIME.match(suffix)
    if match is None:
        return None, ""
    raw_value = match.group(0)
    try:
        value = time(
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
        )
    except ValueError:
        logger.warning(
            "Ignoring invalid time-like value %s in filename %s", raw_value, filename
        )
        return None, raw_value
    return value, raw_value


def extract_filename_date(
    path: Path, logger: logging.Logger | None = None
) -> FilenameDate | None:
    """Return an unambiguous valid date explicitly present in ``path.name``."""

    active_logger = logger or logging.getLogger(__name__)
    filename = path.name
    candidates: list[FilenameDate] = []
    saw_date_like_value = False

    for pattern, expression in _DATE_PATTERNS:
        for match in expression.finditer(filename):
            saw_date_like_value = True
            raw_value = match.group(0)
            try:
                value = date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            except ValueError:
                active_logger.warning(
                    "Ignoring invalid date-like value %s in filename %s",
                    raw_value,
                    filename,
                )
                continue
            capture_time, time_raw_value = _extract_filename_time(
                filename[match.end() :], filename, active_logger
            )
            candidates.append(
                FilenameDate(
                    value=value,
                    source=f"filename.{pattern}",
                    pattern=pattern,
                    raw_value=raw_value + time_raw_value,
                    capture_time=capture_time,
                )
            )

    distinct_dates = {candidate.value for candidate in candidates}
    if len(distinct_dates) > 1:
        active_logger.warning(
            "Ignoring ambiguous dates in filename %s: %s",
            filename,
            ", ".join(sorted(str(value) for value in distinct_dates)),
        )
        return None
    if not candidates:
        if saw_date_like_value:
            active_logger.warning("No valid date found in filename %s", filename)
        return None

    result = candidates[0]
    active_logger.info(
        "Using filename date %s from %s (%s)",
        result.value,
        filename,
        result.pattern,
    )
    return result


def extract_path_date(
    path: Path, logger: logging.Logger | None = None
) -> FilenameDate | None:
    """Return a valid ``YYYY/MMDD`` date encoded by path components."""
    active_logger = logger or logging.getLogger(__name__)
    parts = path.parts
    candidates: list[FilenameDate] = []
    saw_date_like_value = False

    for index, component in enumerate(parts):
        match = _PATH_MONTH_DAY.match(component)
        if match is None:
            continue
        saw_date_like_value = True
        year = next(
            (
                year_match.group("year")
                for previous in reversed(parts[:index])
                if (year_match := _PATH_YEAR.match(previous)) is not None
            ),
            None,
        )
        if year is None:
            continue
        raw_value = f"{year}/{match.group(0).split()[0].rstrip('_-')}"
        try:
            value = date(int(year), int(match.group("month")), int(match.group("day")))
        except ValueError:
            active_logger.warning(
                "Ignoring invalid path date-like value %s in %s", raw_value, path
            )
            continue
        candidates.append(
            FilenameDate(
                value=value,
                source="path.year_mmdd",
                pattern="path_year_mmdd",
                raw_value=raw_value,
            )
        )

    distinct_dates = {candidate.value for candidate in candidates}
    if len(distinct_dates) > 1:
        active_logger.warning("Ignoring ambiguous dates in path %s", path)
        return None
    if not candidates:
        if saw_date_like_value:
            active_logger.warning("No valid date found in path %s", path)
        return None
    result = candidates[0]
    active_logger.info("Using path date %s from %s", result.value, path)
    return result


def resolve_media_date(
    path: Path,
    metadata_date: MetadataDate | None,
    logger: logging.Logger | None = None,
) -> ResolvedDate | None:
    """Prefer a metadata date and use the filename date only as a fallback."""

    if metadata_date is not None:
        return ResolvedDate(
            value=metadata_date.value,
            source=metadata_date.source,
            raw_value=metadata_date.raw_value,
            pattern=None,
        )

    filename_date = extract_filename_date(path, logger=logger)
    if filename_date is None:
        filename_date = extract_path_date(path, logger=logger)
    if filename_date is None:
        return None
    return ResolvedDate(
        value=datetime.combine(
            filename_date.value, filename_date.capture_time or time.min
        ),
        source=filename_date.source,
        raw_value=filename_date.raw_value,
        pattern=filename_date.pattern,
    )
