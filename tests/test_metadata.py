"""Tests for capture-date metadata extraction."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import defoutoir.metadata as metadata_module
from defoutoir.metadata import extract_media_date, parse_metadata_date

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "media"


def test_jpeg_exif_original_date_has_priority() -> None:
    """The original capture timestamp must be selected from JPEG EXIF."""
    result = extract_media_date(FIXTURE_ROOT / "jpeg" / "flower.jpg")

    assert result is not None
    assert result.value == datetime(2003, 12, 14, 12, 1, 44)
    assert result.source == "metadata.exif.datetime_original"


def test_raw_file_uses_hachoir_creation_date() -> None:
    """A camera RAW fixture must yield its container creation timestamp."""
    result = extract_media_date(FIXTURE_ROOT / "raw" / "sample.arw")

    assert result is not None
    assert result.value == datetime(2009, 11, 13, 13, 33, 25)
    assert result.source == "metadata.container.creation_date"


def test_all_relevant_fixture_dates_are_safe_to_read() -> None:
    """Supported fixtures must not crash metadata extraction."""
    paths = [
        FIXTURE_ROOT / "jpeg" / "flower.jpg",
        FIXTURE_ROOT / "raw" / "sample.arw",
        FIXTURE_ROOT / "raw" / "jolstravatnet.pef",
    ]

    results = [extract_media_date(path) for path in paths]

    assert all(result is not None for result in results)


def test_exif_precedence_is_original_then_digitized_then_generic(
    tmp_path: Path,
) -> None:
    """The documented EXIF precedence must be deterministic."""
    image_path = tmp_path / "precedence.jpg"
    exif = Image.Exif()
    exif[306] = "2001:01:01 01:01:01"
    exif[36868] = "2002:02:02 02:02:02"
    exif[36867] = "2003:03:03 03:03:03"
    Image.new("RGB", (4, 4), color="red").save(image_path, exif=exif)

    result = extract_media_date(image_path)

    assert result is not None
    assert result.value == datetime(2003, 3, 3, 3, 3, 3)
    assert result.source == "metadata.exif.datetime_original"


def test_iso_and_timezone_dates_are_normalized() -> None:
    """ISO dates with timezone information must normalize to UTC-naive values."""
    assert parse_metadata_date("2024-05-06T08:30:00+02:00") == datetime(
        2024,
        5,
        6,
        6,
        30,
    )
    assert parse_metadata_date("2024-05-06T06:30:00Z") == datetime(
        2024,
        5,
        6,
        6,
        30,
    )


def test_invalid_or_missing_metadata_returns_none(caplog) -> None:
    """Files without a usable date must return None without raising."""
    path = FIXTURE_ROOT / "jpeg" / "hopper.jpg"
    logger = logging.getLogger("tests.metadata")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        result = extract_media_date(path, logger=logger)

    assert result is None
    assert any("No usable metadata date" in record.message for record in caplog.records)


def test_movie_metadata_adapter_can_supply_a_date(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Movie paths must use the container adapter when it returns a date."""
    expected = datetime(2022, 7, 8, 9, 10, 11)
    movie_path = tmp_path / "movie.mp4"
    movie_path.write_bytes(b"not a complete movie")

    def fake_hachoir(_path, _logger):
        return (
            SimpleNamespace(
                value=expected,
                source="metadata.container.creation_date",
                raw_value=str(expected),
                priority=2,
            ),
        )

    monkeypatch.setattr(metadata_module, "_extract_hachoir_candidates", fake_hachoir)

    result = extract_media_date(movie_path)

    assert result is not None
    assert result.value == expected
    assert result.source == "metadata.container.creation_date"


def test_unsupported_path_returns_none(tmp_path: Path) -> None:
    """Unsupported extensions must not invoke metadata readers."""
    text_path = tmp_path / "notes.txt"
    text_path.write_text("not media", encoding="utf-8")

    assert extract_media_date(text_path) is None
