"""Capture-date extraction from image, RAW, and video metadata."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple

from hachoir.core.log import log as HACHOIR_LOG
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from PIL import Image

from defoutoir.log import get_logger
from defoutoir.scanner import PICTURE_EXTENSIONS

EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME_DIGITIZED = 36868
EXIF_DATETIME = 306
EXIF_IFD_POINTER = 34665
RASTER_EXTENSIONS = PICTURE_EXTENSIONS.intersection(
    ".bmp .gif .heic .heif .jpeg .jpg .png .tif .tiff .webp".split()
)


class MetadataDate(NamedTuple):
    """A normalized capture date and the metadata field that supplied it."""

    value: datetime
    source: str
    raw_value: str


class _DateCandidate(NamedTuple):
    """An intermediate candidate before precedence is applied."""

    value: datetime
    source: str
    raw_value: str
    priority: int


def extract_media_date(
    path: str | Path,
    logger: logging.Logger | None = None,
) -> MetadataDate | None:
    """Extract the preferred capture date without modifying the media file."""
    media_path = Path(path)
    active_logger = logger or get_logger("metadata")
    candidates: list[_DateCandidate] = []

    is_raster = media_path.suffix.casefold() in RASTER_EXTENSIONS
    if is_raster:
        candidates.extend(_extract_pillow_candidates(media_path, active_logger))
    else:
        candidates.extend(_extract_hachoir_candidates(media_path, active_logger))

    if not candidates:
        active_logger.debug("No usable metadata date: %s", media_path)
        return None

    selected = min(candidates, key=lambda candidate: candidate.priority)
    result = MetadataDate(
        value=selected.value,
        source=selected.source,
        raw_value=selected.raw_value,
    )
    active_logger.info(
        "Metadata date selected for %s: %s (%s)",
        media_path,
        result.value.isoformat(sep=" "),
        result.source,
    )
    return result


def parse_metadata_date(value: object) -> datetime | None:
    """Parse common EXIF, ISO, Hachoir, and date-only values."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="replace")
        if not isinstance(value, str):
            return None
        text = value.strip().replace("\x00", "")
        if not text:
            return None
        parsed = _parse_date_text(text)
        if parsed is None:
            return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _extract_pillow_candidates(
    path: Path,
    logger: logging.Logger,
) -> tuple[_DateCandidate, ...]:
    """Read EXIF tags from raster files with Pillow."""
    candidates: list[_DateCandidate] = []
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)
            values = {
                EXIF_DATETIME_ORIGINAL: exif_ifd.get(
                    EXIF_DATETIME_ORIGINAL,
                    exif.get(EXIF_DATETIME_ORIGINAL),
                ),
                EXIF_DATETIME_DIGITIZED: exif_ifd.get(
                    EXIF_DATETIME_DIGITIZED,
                    exif.get(EXIF_DATETIME_DIGITIZED),
                ),
                EXIF_DATETIME: exif.get(EXIF_DATETIME),
            }
    except (OSError, ValueError) as error:
        logger.warning("Could not read image metadata from %s: %s", path, error)
        return ()

    source_by_tag = {
        EXIF_DATETIME_ORIGINAL: ("metadata.exif.datetime_original", 0),
        EXIF_DATETIME_DIGITIZED: ("metadata.exif.datetime_digitized", 1),
        EXIF_DATETIME: ("metadata.exif.datetime", 2),
    }
    invalid_count = 0
    for tag, raw_value in values.items():
        candidate = _make_candidate(raw_value, source_by_tag[tag])
        if candidate is not None:
            candidates.append(candidate)
        elif raw_value is not None:
            invalid_count += 1
    if invalid_count:
        logger.warning(
            "Ignoring %d invalid EXIF date value(s) in %s", invalid_count, path
        )
    return tuple(candidates)


def _extract_hachoir_candidates(
    path: Path,
    logger: logging.Logger,
) -> tuple[_DateCandidate, ...]:
    """Read container and RAW metadata with Hachoir."""
    try:
        with _quiet_hachoir_output():
            parser = createParser(str(path))
            if parser is None:
                return ()
            with parser:
                metadata = extractMetadata(parser)
                if metadata is None:
                    return ()
                candidates = []
                for key, source, priority in (
                    ("date_time_original", "metadata.exif.datetime_original", 0),
                    ("date_time_digitized", "metadata.exif.datetime_digitized", 1),
                    ("creation_date", "metadata.container.creation_date", 2),
                ):
                    try:
                        raw_value = metadata.get(key)
                    except (IndexError, KeyError, ValueError):
                        continue
                    parsed = parse_metadata_date(raw_value)
                    if parsed is not None:
                        candidates.append(
                            _DateCandidate(
                                value=parsed,
                                source=source,
                                raw_value=str(raw_value),
                                priority=priority,
                            )
                        )
                    elif raw_value is not None:
                        logger.warning(
                            "Ignoring invalid container date in %s: %r",
                            path,
                            raw_value,
                        )
                return tuple(candidates)
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning("Could not read container metadata from %s: %s", path, error)
        return ()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.warning("Unexpected metadata error for %s: %s", path, error)
        return ()


@contextmanager
def _quiet_hachoir_output():
    """Prevent Hachoir's legacy stderr warnings from polluting the CLI."""
    previous_use_print = HACHOIR_LOG.use_print
    HACHOIR_LOG.use_print = False
    try:
        yield
    finally:
        HACHOIR_LOG.use_print = previous_use_print


def _make_candidate(
    raw_value: object,
    source_info: tuple[str, int],
) -> _DateCandidate | None:
    """Parse one EXIF value into a metadata candidate."""
    if raw_value is None:
        return None
    parsed = parse_metadata_date(raw_value)
    if parsed is None:
        return None
    return _DateCandidate(
        value=parsed,
        source=source_info[0],
        raw_value=str(raw_value),
        priority=source_info[1],
    )


def _parse_date_text(text: str) -> datetime | None:
    """Parse EXIF colon-separated and ISO date representations."""
    if len(text) >= 19 and text[4] == ":" and text[7] == ":":
        text = text[:19]
        try:
            return datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
