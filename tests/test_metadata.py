"""Tests for capture-date metadata extraction."""

# pylint: disable=protected-access

from __future__ import annotations

import logging
from datetime import date, datetime
from io import BytesIO
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


def test_canon_cr2_reads_exif_capture_date_before_hachoir() -> None:
    """Canon CR2 EXIF must be preferred when Hachoir cannot parse all IFDs."""
    result = extract_media_date(FIXTURE_ROOT / "raw" / "sample.cr2")

    assert result is not None
    assert result.value == datetime(2011, 8, 24, 14, 41, 4)
    assert result.source == "metadata.exif.datetime_original"


def test_real_canon_cr2_reads_generic_exif_capture_date() -> None:
    """A real Canon CR2 with a generic EXIF date must still be cataloged."""
    result = extract_media_date(FIXTURE_ROOT / "raw" / "_MG_8968.CR2")

    assert result is not None
    assert result.value == datetime(2022, 4, 17, 0, 36, 51)
    assert result.source == "metadata.exif.datetime_original"


def test_lightroom_dng_reads_capture_date_from_exif() -> None:
    """A Lightroom DNG must not fall back to its later container date."""
    result = extract_media_date(FIXTURE_ROOT / "raw" / "_MG_3055.dng")

    assert result is not None
    assert result.value == datetime(2013, 6, 29, 11, 57, 49)
    assert result.source == "metadata.exif.datetime_original"


def test_fujifilm_raf_reads_exif_from_embedded_jpeg(tmp_path: Path) -> None:
    """A Fujifilm RAF must expose the capture date from its JPEG preview."""
    preview_stream = BytesIO()
    exif = Image.Exif()
    exif[36867] = "2018:07:28 09:10:11"
    Image.new("RGB", (8, 6), color="green").save(
        preview_stream, format="JPEG", exif=exif
    )
    preview = preview_stream.getvalue()
    header = bytearray(metadata_module.RAF_HEADER_SIZE)
    header[:16] = b"FUJIFILMCCD-RAW "
    header[84:88] = metadata_module.RAF_HEADER_SIZE.to_bytes(4, "big")
    header[88:92] = len(preview).to_bytes(4, "big")
    raf_path = tmp_path / "_DSF0044.RAF"
    raf_path.write_bytes(bytes(header) + preview)

    result = extract_media_date(raf_path)

    assert result is not None
    assert result.value == datetime(2018, 7, 28, 9, 10, 11)
    assert result.source == "metadata.exif.datetime_original"


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


def test_date_only_metadata_uses_noon_but_explicit_midnight_is_preserved() -> None:
    """Only an absent time is replaced with noon."""
    assert parse_metadata_date(date(2024, 5, 6)) == datetime(2024, 5, 6, 12)
    assert parse_metadata_date("2024-05-06") == datetime(2024, 5, 6, 12)
    assert parse_metadata_date("20240506") == datetime(2024, 5, 6, 12)
    assert parse_metadata_date("2024-05-06T00:00:00") == datetime(2024, 5, 6)


def test_invalid_or_missing_metadata_returns_none(caplog) -> None:
    """Files without a usable date must return None without raising."""
    path = FIXTURE_ROOT / "jpeg" / "hopper.jpg"
    logger = logging.getLogger("tests.metadata")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        result = extract_media_date(path, logger=logger)

    assert result is None
    assert any("No usable metadata date" in record.message for record in caplog.records)


def test_raster_with_invalid_exif_does_not_fall_through_to_hachoir(
    tmp_path: Path, monkeypatch
) -> None:
    """Malformed raster EXIF must not trigger noisy container parsing."""
    image_path = tmp_path / "invalid.jpg"
    exif = Image.Exif()
    exif[36867] = "    :  :     :  :  "
    Image.new("RGB", (4, 4), color="red").save(image_path, exif=exif)

    def fail_hachoir(_path, _logger):
        raise AssertionError("Hachoir must not parse raster fallback metadata")

    monkeypatch.setattr(metadata_module, "_extract_hachoir_candidates", fail_hachoir)

    assert extract_media_date(image_path) is None


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


def test_xmp_metadata_is_read_in_bounded_chunks(tmp_path: Path) -> None:
    """XMP extraction must find tags without loading the whole media file."""
    movie_path = tmp_path / "large.mp4"
    prefix = b"x" * (metadata_module.XMP_READ_CHUNK_SIZE - 8)
    movie_path.write_bytes(
        prefix
        + b'photoshop:DateCreated="2024-07-29"'
        + b"x" * (metadata_module.XMP_READ_CHUNK_SIZE * 2)
    )

    candidates = metadata_module._extract_xmp_candidates(
        movie_path, logging.getLogger("tests.metadata")
    )

    assert len(candidates) == 1
    assert candidates[0].value == datetime(2024, 7, 29, 12)


def test_invalid_movie_container_does_not_write_hachoir_warnings(
    tmp_path: Path, capsys
) -> None:
    """Malformed movie containers must keep Hachoir diagnostics out of the CLI."""
    movie_path = tmp_path / "broken.MOV"
    movie_path.write_bytes(b"not a valid movie")

    assert extract_media_date(movie_path) is None
    assert "[warn]" not in capsys.readouterr().err


def test_unsupported_path_returns_none(tmp_path: Path) -> None:
    """Unsupported extensions must not invoke metadata readers."""
    text_path = tmp_path / "notes.txt"
    text_path.write_text("not media", encoding="utf-8")

    assert extract_media_date(text_path) is None
