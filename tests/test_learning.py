"""Tests for catalog-only learning state transitions."""

# pylint: disable=missing-function-docstring

from pathlib import Path

import defoutoir.catalog as catalog_module
from defoutoir.catalog import MediaCatalog
from defoutoir.learning import learn_media


def test_first_and_repeated_learn_are_classified(tmp_path: Path) -> None:
    source = tmp_path / "IMG_20240102.jpg"
    source.write_bytes(b"photo")
    with MediaCatalog(":memory:") as catalog:
        first = learn_media((source,), (tmp_path,), catalog)
        repeated = learn_media((source,), (tmp_path,), catalog)

        assert first.summary == {"learned": 1}
        assert repeated.summary == {"unchanged": 1}
        assert repeated.records[0].media_date == "2024-01-02 12:00:00"


def test_changed_file_is_updated(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"before")
    with MediaCatalog(":memory:") as catalog:
        learn_media((source,), (tmp_path,), catalog)
        source.write_bytes(b"after")

        result = learn_media((source,), (tmp_path,), catalog)

        assert result.summary == {"updated": 1}


def test_unchanged_file_reuses_persisted_metadata(tmp_path: Path, monkeypatch) -> None:
    """A resumed run must not hash or extract an unchanged file again."""
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"photo")
    with MediaCatalog(":memory:") as catalog:
        learn_media((source,), (tmp_path,), catalog)

        def fail_metadata(*_args, **_kwargs):
            raise AssertionError("metadata extraction should be skipped")

        def fail_hash(*_args, **_kwargs):
            raise AssertionError("content hashing should be skipped")

        monkeypatch.setattr("defoutoir.learning.extract_media_date", fail_metadata)
        monkeypatch.setattr(catalog_module, "calculate_sha1", fail_hash)
        result = learn_media((source,), (tmp_path,), catalog)

        assert result.summary == {"unchanged": 1}


def test_duplicate_files_are_explicitly_classified(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    with MediaCatalog(":memory:") as catalog:
        result = learn_media((first, second), (tmp_path,), catalog)

        assert result.summary == {"duplicate": 1, "learned": 1}
        assert catalog.get_by_path(second).processing_state == "duplicate"


def test_cached_whatsapp_video_date_is_refreshed_without_rehashing(
    tmp_path: Path, monkeypatch
) -> None:
    """Old cached container dates must migrate to the authoritative filename."""
    source = tmp_path / "VID-20180728-WA0008.mp4"
    source.write_bytes(b"video")
    with MediaCatalog(":memory:") as catalog:
        catalog.record_file(
            source,
            media_date="2024-01-02 03:04:05",
            date_source="container.creation_date",
            processing_state="learned",
        )

        def fail_hash(*_args, **_kwargs):
            raise AssertionError("content hashing should be skipped")

        monkeypatch.setattr(catalog_module, "calculate_sha1", fail_hash)
        result = learn_media((source,), (tmp_path,), catalog)

        assert result.records[0].media_date == "2018-07-28 12:00:00"
        assert result.records[0].date_source == "filename.whatsapp_video_yyyymmdd"


def test_removed_file_is_marked_missing(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"photo")
    with MediaCatalog(":memory:") as catalog:
        learn_media((source,), (tmp_path,), catalog)
        source.unlink()

        result = learn_media((), (tmp_path,), catalog)

        assert result.summary == {"missing": 1}
        assert catalog.get_by_path(source).processing_state == "missing"


def test_learn_never_creates_an_output_directory(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"photo")
    output = tmp_path / "output"
    with MediaCatalog(":memory:") as catalog:
        learn_media((source,), (tmp_path,), catalog)

    assert source.read_bytes() == b"photo"
    assert not output.exists()
