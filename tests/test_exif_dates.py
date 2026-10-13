"""Tests for lossless conditional EXIF date updates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image

from defoutoir.exif_dates import ExifDateStatus, write_missing_exif_date
from defoutoir.metadata import extract_media_date


def _create_image(path: Path, exif: Image.Exif | None = None) -> None:
    """Create a small real image in the format selected by its suffix."""
    options = {"exif": exif} if exif is not None else {}
    Image.new("RGB", (8, 6), color=(20, 80, 140)).save(path, **options)


def test_jpeg_receives_original_date_without_changing_pixels(tmp_path: Path) -> None:
    """JPEG EXIF insertion must preserve decoded pixels exactly."""
    path = tmp_path / "photo.jpg"
    _create_image(path)
    with Image.open(path) as image:
        pixels_before = image.tobytes()

    status = write_missing_exif_date(path, datetime(2024, 1, 2, 3, 4, 5))

    assert status is ExifDateStatus.WRITTEN
    result = extract_media_date(path)
    assert result is not None
    assert result.value == datetime(2024, 1, 2, 3, 4, 5)
    assert result.source == "metadata.exif.datetime_original"
    with Image.open(path) as image:
        assert image.tobytes() == pixels_before


def test_png_receives_original_date_without_changing_pixels(tmp_path: Path) -> None:
    """PNG eXIf insertion must preserve decoded pixels exactly."""
    path = tmp_path / "photo.png"
    _create_image(path)
    with Image.open(path) as image:
        pixels_before = image.tobytes()

    status = write_missing_exif_date(path, datetime(2023, 7, 8, 9, 10, 11))

    assert status is ExifDateStatus.WRITTEN
    result = extract_media_date(path)
    assert result is not None
    assert result.value == datetime(2023, 7, 8, 9, 10, 11)
    with Image.open(path) as image:
        assert image.tobytes() == pixels_before


def test_existing_date_is_never_replaced(tmp_path: Path) -> None:
    """A valid existing capture date must leave the complete file untouched."""
    path = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[36867] = "2001:02:03 04:05:06"
    _create_image(path, exif)
    before = path.read_bytes()

    status = write_missing_exif_date(path, datetime(2024, 1, 2, 3, 4, 5))

    assert status is ExifDateStatus.ALREADY_DATED
    assert path.read_bytes() == before


def test_unsupported_file_is_not_modified(tmp_path: Path) -> None:
    """Formats without a safe adapter must be reported and preserved."""
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"movie")

    status = write_missing_exif_date(path, datetime(2024, 1, 2))

    assert status is ExifDateStatus.UNSUPPORTED
    assert path.read_bytes() == b"movie"
