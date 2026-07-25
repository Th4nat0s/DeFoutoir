"""Tests for catalog-only learning state transitions."""

# pylint: disable=missing-function-docstring

from pathlib import Path

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
        assert repeated.records[0].media_date == "2024-01-02 00:00:00"


def test_changed_file_is_updated(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"before")
    with MediaCatalog(":memory:") as catalog:
        learn_media((source,), (tmp_path,), catalog)
        source.write_bytes(b"after")

        result = learn_media((source,), (tmp_path,), catalog)

        assert result.summary == {"updated": 1}


def test_duplicate_files_are_explicitly_classified(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    with MediaCatalog(":memory:") as catalog:
        result = learn_media((first, second), (tmp_path,), catalog)

        assert result.summary == {"duplicate": 1, "learned": 1}
        assert catalog.get_by_path(second).processing_state == "duplicate"


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
