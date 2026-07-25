"""Tests for filename date extraction and fallback selection."""

# pylint: disable=missing-function-docstring

from datetime import date, datetime
from pathlib import Path

import pytest

from defoutoir import filename_dates
from defoutoir.metadata import MetadataDate


@pytest.mark.parametrize(
    ("filename", "expected", "pattern"),
    [
        ("IMG_20240102_123456.JPG", date(2024, 1, 2), "compact_yyyymmdd"),
        ("VID_2024-12-31_235959.mp4", date(2024, 12, 31), "separated_yyyy_mm_dd"),
        ("IMG_2024_07_09.jpg", date(2024, 7, 9), "separated_yyyy_mm_dd"),
        ("photo.2023.03.08.png", date(2023, 3, 8), "separated_yyyy_mm_dd"),
    ],
)
def test_extract_filename_date_supports_documented_patterns(
    filename: str, expected: date, pattern: str
) -> None:
    result = filename_dates.extract_filename_date(Path(filename))

    assert result is not None
    assert result.value == expected
    assert result.pattern == pattern


@pytest.mark.parametrize(
    "filename",
    [
        "IMG_20240230.jpg",
        "IMG_2024-13-01.jpg",
        "DSC_12345678.jpg",
        "IMG_01022024.jpg",
        "holiday_notes.txt",
    ],
)
def test_extract_filename_date_rejects_invalid_ambiguous_or_unrelated_names(
    filename: str,
) -> None:
    assert filename_dates.extract_filename_date(Path(filename)) is None


def test_extract_filename_date_rejects_multiple_distinct_dates() -> None:
    result = filename_dates.extract_filename_date(Path("20240101-20240202.jpg"))

    assert result is None


def test_resolve_media_date_prefers_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata_date = MetadataDate(
        value=datetime(2024, 1, 2, 3, 4, 5),
        source="exif.datetime_original",
        raw_value="2024:01:02 03:04:05",
    )

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("filename fallback called")

    monkeypatch.setattr(filename_dates, "extract_filename_date", fail_if_called)
    result = filename_dates.resolve_media_date(Path("IMG_20240103.jpg"), metadata_date)

    assert result is not None
    assert result.value == metadata_date.value
    assert result.source == metadata_date.source


def test_resolve_media_date_uses_filename_at_midnight() -> None:
    result = filename_dates.resolve_media_date(Path("IMG_2024-01-03.jpg"), None)

    assert result is not None
    assert result.value == datetime(2024, 1, 3)
    assert result.source == "filename.separated_yyyy_mm_dd"
    assert result.pattern == "separated_yyyy_mm_dd"


def test_resolve_media_date_returns_none_without_any_date() -> None:
    assert filename_dates.resolve_media_date(Path("readme.txt"), None) is None


def test_extract_path_date_supports_album_year_and_month_day() -> None:
    """Album paths such as 2002/0208 Wicher resolve to 8 February 2002."""
    result = filename_dates.extract_path_date(
        Path("Albums/2002/0208 Wicher/.AppleDouble/26 - P210A - Moyeuvre.jpg")
    )

    assert result is not None
    assert result.value == date(2002, 2, 8)
    assert result.source == "path.year_mmdd"
    assert result.raw_value == "2002/0208"


def test_resolve_media_date_uses_path_after_filename() -> None:
    """Path dates are the final fallback when metadata and filename are empty."""
    result = filename_dates.resolve_media_date(
        Path("Albums/2002/0208 Wicher/photo.jpg"), None
    )

    assert result is not None
    assert result.value == datetime(2002, 2, 8)
    assert result.source == "path.year_mmdd"
