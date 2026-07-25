"""Tests for the SQLite media catalog."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from defoutoir.catalog import (
    DEFAULT_DATABASE_PATH,
    HASH_CHUNK_SIZE,
    SCHEMA_VERSION,
    CatalogError,
    MediaCatalog,
    calculate_sha1,
)


def create_file(path: Path, content: bytes) -> Path:
    """Create a test file and return its resolved path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path.resolve()


def test_catalog_creates_versioned_schema(tmp_path: Path) -> None:
    """Opening a new database must create tables and indexes."""
    database = tmp_path / "state" / "catalog.sqlite3"

    with MediaCatalog(database) as catalog:
        assert catalog.schema_version == SCHEMA_VERSION
        assert catalog.count == 0

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert {"schema_meta", "media_files"} <= tables
    assert "idx_media_files_sha1" in indexes
    assert "idx_media_files_media_date" in indexes


def test_default_database_path_is_configurable() -> None:
    """The documented default must remain a relative configurable path."""
    assert DEFAULT_DATABASE_PATH == Path("defoutoir.sqlite3")
    assert MediaCatalog().database_path == DEFAULT_DATABASE_PATH


def test_record_stores_hash_file_data_and_date(tmp_path: Path) -> None:
    """A record must persist identity, timestamps, date, and state."""
    media_file = create_file(tmp_path / "photo.jpg", b"photo contents")

    with MediaCatalog(tmp_path / "catalog.sqlite3") as catalog:
        record = catalog.record_file(
            media_file,
            media_date="2024-05-06T07:08:09",
            date_source="metadata",
            processing_state="learned",
        )

        assert record.source_path == str(media_file)
        assert record.sha1 == hashlib.sha1(b"photo contents").hexdigest()
        assert record.size_bytes == len(b"photo contents")
        assert record.modified_ns > 0
        assert record.metadata_changed_ns > 0
        assert record.media_date == "2024-05-06T07:08:09"
        assert record.date_source == "metadata"
        assert record.processing_state == "learned"
        assert catalog.get_by_path(media_file) == record
        assert catalog.count == 1


def test_recording_unchanged_file_is_idempotent(tmp_path: Path) -> None:
    """Recording the same unchanged file must reuse its row identity."""
    media_file = create_file(tmp_path / "photo.png", b"same bytes")

    with MediaCatalog(tmp_path / "catalog.sqlite3") as catalog:
        first = catalog.record_file(media_file)
        second = catalog.record_file(media_file)

        assert second.id == first.id
        assert second.sha1 == first.sha1
        assert catalog.count == 1


def test_changed_file_updates_existing_row(tmp_path: Path) -> None:
    """A changed file must update its row rather than create a duplicate."""
    media_file = create_file(tmp_path / "photo.png", b"before")

    with MediaCatalog(tmp_path / "catalog.sqlite3") as catalog:
        first = catalog.record_file(media_file)
        media_file.write_bytes(b"after with more bytes")
        second = catalog.record_file(media_file)

        assert second.id == first.id
        assert second.sha1 != first.sha1
        assert second.size_bytes == len(b"after with more bytes")
        assert catalog.count == 1


def test_sha1_is_calculated_in_chunks(tmp_path: Path) -> None:
    """Hashing must support data larger than one configured chunk."""
    content = bytes(range(256)) * ((HASH_CHUNK_SIZE // 256) + 2)
    media_file = create_file(tmp_path / "large.mov", content)

    assert calculate_sha1(media_file) == hashlib.sha1(content).hexdigest()


def test_duplicate_groups_find_same_content(tmp_path: Path) -> None:
    """Files with identical bytes must be returned as one duplicate group."""
    first = create_file(tmp_path / "first.jpg", b"duplicate")
    second = create_file(tmp_path / "nested" / "second.jpg", b"duplicate")

    with MediaCatalog(tmp_path / "catalog.sqlite3") as catalog:
        first_record = catalog.record_file(first)
        second_record = catalog.record_file(second)

        assert catalog.find_by_sha1(first_record.sha1) == (
            first_record,
            second_record,
        )
        assert catalog.duplicate_groups() == ((first_record, second_record),)


def test_media_date_can_be_updated_after_cataloging(tmp_path: Path) -> None:
    """Date extraction can enrich an existing catalog record later."""
    media_file = create_file(tmp_path / "photo.jpg", b"photo")

    with MediaCatalog(tmp_path / "catalog.sqlite3") as catalog:
        catalog.record_file(media_file)
        record = catalog.update_media_date(
            media_file,
            media_date="2020-01-02",
            date_source="filename",
        )

        assert record.media_date == "2020-01-02"
        assert record.date_source == "filename"


def test_batch_transaction_rolls_back_on_failure(tmp_path: Path) -> None:
    """A failed batch must not leave earlier rows partially committed."""
    valid_file = create_file(tmp_path / "valid.jpg", b"valid")
    missing_file = tmp_path / "missing.jpg"

    with MediaCatalog(tmp_path / "catalog.sqlite3") as catalog:
        with pytest.raises(CatalogError):
            catalog.record_files([valid_file, missing_file])

        assert catalog.count == 0


def test_context_closes_connection_and_rejects_later_operations(
    tmp_path: Path,
) -> None:
    """The context manager must close resources deterministically."""
    catalog = MediaCatalog(tmp_path / "catalog.sqlite3")
    catalog.open()
    catalog.close()

    with pytest.raises(CatalogError, match="catalog is closed"):
        _ = catalog.count
