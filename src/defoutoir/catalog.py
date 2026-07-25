"""SQLite catalog and content identity operations for DeFoutoir."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from defoutoir.log import get_logger

DEFAULT_DATABASE_PATH = Path("defoutoir.sqlite3")
SCHEMA_VERSION = 1
HASH_CHUNK_SIZE = 1024 * 1024


class CatalogError(RuntimeError):
    """Raise when a media catalog operation cannot be completed."""


class MediaRecord(NamedTuple):
    """A catalog row describing one source media file."""

    id: int
    source_path: str
    sha1: str
    size_bytes: int
    modified_ns: int
    metadata_changed_ns: int
    media_date: str | None
    date_source: str | None
    processing_state: str
    created_at_ns: int
    updated_at_ns: int


class _FileSnapshot(NamedTuple):
    """Immutable file data collected before a catalog write."""

    source_path: str
    sha1: str
    size_bytes: int
    modified_ns: int
    metadata_changed_ns: int
    updated_at_ns: int


class MediaCatalog:
    """Manage a versioned SQLite catalog of discovered media files."""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self._logger = logger or get_logger("catalog")
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "MediaCatalog":
        """Open the catalog for use in a context manager."""
        self.open()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        """Close the catalog connection after the context ends."""
        self.close()

    def open(self) -> None:
        """Open the database and create its schema if necessary."""
        if self._connection is not None:
            return

        try:
            if str(self.database_path) != ":memory:":
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.database_path))
            connection.execute("PRAGMA foreign_keys = ON")
            self._initialize_schema(connection)
        except (OSError, sqlite3.Error, CatalogError) as error:
            if "connection" in locals():
                connection.close()
            raise CatalogError(
                f"Could not open media catalog {self.database_path}: {error}"
            ) from error

        self._connection = connection
        self._logger.info("Opened media catalog: %s", self.database_path)

    def close(self) -> None:
        """Close the database connection if it is open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def schema_version(self) -> int:
        """Return the current catalog schema version."""
        row = (
            self._connection_or_raise()
            .execute("SELECT value FROM schema_meta WHERE key = 'version'")
            .fetchone()
        )
        if row is None:
            raise CatalogError("Media catalog schema version is missing")
        return int(row[0])

    @property
    def count(self) -> int:
        """Return the number of cataloged media files."""
        row = (
            self._connection_or_raise()
            .execute("SELECT COUNT(*) FROM media_files")
            .fetchone()
        )
        return int(row[0])

    def record_file(
        self,
        path: str | Path,
        media_date: str | None = None,
        date_source: str | None = None,
        processing_state: str = "discovered",
    ) -> MediaRecord:
        """Hash and upsert one media file in a transaction."""
        records = self._record_paths(
            [path],
            media_date=media_date,
            date_source=date_source,
            processing_state=processing_state,
        )
        return records[0]

    def record_files(self, paths: Iterable[str | Path]) -> tuple[MediaRecord, ...]:
        """Hash and upsert multiple files atomically."""
        return self._record_paths(paths)

    def update_media_date(
        self,
        path: str | Path,
        media_date: str | None,
        date_source: str | None,
    ) -> MediaRecord:
        """Update the resolved media date and its extraction source."""
        source_path = self._normalize_lookup_path(path)
        connection = self._connection_or_raise()
        updated_at_ns = time.time_ns()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE media_files
                    SET media_date = ?, date_source = ?, updated_at_ns = ?
                    WHERE source_path = ?
                    """,
                    (media_date, date_source, updated_at_ns, source_path),
                )
                if cursor.rowcount != 1:
                    raise CatalogError(f"Media file is not cataloged: {source_path}")
        except (CatalogError, sqlite3.Error) as error:
            self._logger.error("Could not update media date for %s: %s", path, error)
            if isinstance(error, CatalogError):
                raise
            raise CatalogError(
                f"Could not update media date for {source_path}: {error}"
            ) from error

        record = self.get_by_path(source_path)
        if record is None:
            raise CatalogError(f"Media file disappeared from catalog: {source_path}")
        self._logger.info("Updated media date: %s", source_path)
        return record

    def update_processing_state(self, path: str | Path, state: str) -> MediaRecord:
        """Record the latest planning or execution state for one media file."""
        source_path = self._normalize_lookup_path(path)
        connection = self._connection_or_raise()
        updated_at_ns = time.time_ns()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE media_files
                    SET processing_state = ?, updated_at_ns = ?
                    WHERE source_path = ?
                    """,
                    (state, updated_at_ns, source_path),
                )
                if cursor.rowcount != 1:
                    raise CatalogError(f"Media file is not cataloged: {source_path}")
        except (CatalogError, sqlite3.Error) as error:
            self._logger.error(
                "Could not update processing state for %s: %s", path, error
            )
            if isinstance(error, CatalogError):
                raise
            raise CatalogError(
                f"Could not update processing state for {source_path}: {error}"
            ) from error

        record = self.get_by_path(source_path)
        if record is None:
            raise CatalogError(f"Media file disappeared from catalog: {source_path}")
        self._logger.info("Updated processing state for %s: %s", source_path, state)
        return record

    def get_by_path(self, path: str | Path) -> MediaRecord | None:
        """Return the record for a normalized source path, if present."""
        source_path = self._normalize_lookup_path(path)
        row = (
            self._connection_or_raise()
            .execute(
                """
            SELECT id, source_path, sha1, size_bytes, modified_ns,
                   metadata_changed_ns, media_date, date_source,
                   processing_state, created_at_ns, updated_at_ns
            FROM media_files
            WHERE source_path = ?
            """,
                (source_path,),
            )
            .fetchone()
        )
        return _row_to_record(row) if row is not None else None

    def find_by_sha1(self, sha1: str) -> tuple[MediaRecord, ...]:
        """Return all files with a given SHA-1 content identity."""
        rows = (
            self._connection_or_raise()
            .execute(
                """
            SELECT id, source_path, sha1, size_bytes, modified_ns,
                   metadata_changed_ns, media_date, date_source,
                   processing_state, created_at_ns, updated_at_ns
            FROM media_files
            WHERE sha1 = ?
            ORDER BY source_path
            """,
                (sha1,),
            )
            .fetchall()
        )
        return tuple(_row_to_record(row) for row in rows)

    def duplicate_groups(self) -> tuple[tuple[MediaRecord, ...], ...]:
        """Return groups containing more than one file with the same hash."""
        rows = self._connection_or_raise().execute("""
            SELECT sha1
            FROM media_files
            GROUP BY sha1
            HAVING COUNT(*) > 1
            ORDER BY sha1
            """).fetchall()
        return tuple(self.find_by_sha1(row[0]) for row in rows)

    def all_records(self) -> tuple[MediaRecord, ...]:
        """Return all records in deterministic source-path order."""
        rows = self._connection_or_raise().execute("""
            SELECT id, source_path, sha1, size_bytes, modified_ns,
                   metadata_changed_ns, media_date, date_source,
                   processing_state, created_at_ns, updated_at_ns
            FROM media_files
            ORDER BY source_path
            """).fetchall()
        return tuple(_row_to_record(row) for row in rows)

    def _record_paths(
        self,
        paths: Iterable[str | Path],
        media_date: str | None = None,
        date_source: str | None = None,
        processing_state: str = "discovered",
    ) -> tuple[MediaRecord, ...]:
        connection = self._connection_or_raise()
        source_paths: list[str] = []
        try:
            with connection:
                for path in paths:
                    snapshot = _create_snapshot(path)
                    self._upsert_snapshot(
                        connection,
                        snapshot,
                        media_date,
                        date_source,
                        processing_state,
                    )
                    source_paths.append(snapshot.source_path)
        except (CatalogError, OSError, sqlite3.Error) as error:
            self._logger.error("Catalog transaction failed: %s", error)
            if isinstance(error, CatalogError):
                raise
            raise CatalogError(f"Catalog transaction failed: {error}") from error

        records = tuple(self.get_by_path(path) for path in source_paths)
        if any(record is None for record in records):
            raise CatalogError("Catalog transaction completed without all records")
        self._logger.info("Cataloged %d media file(s).", len(records))
        return tuple(record for record in records if record is not None)

    @staticmethod
    def _upsert_snapshot(
        connection: sqlite3.Connection,
        snapshot: _FileSnapshot,
        media_date: str | None,
        date_source: str | None,
        processing_state: str,
    ) -> None:
        """Insert or update one snapshot inside the caller transaction."""
        connection.execute(
            """
            INSERT INTO media_files (
                source_path, sha1, size_bytes, modified_ns,
                metadata_changed_ns, media_date, date_source,
                processing_state, created_at_ns, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
                sha1 = excluded.sha1,
                size_bytes = excluded.size_bytes,
                modified_ns = excluded.modified_ns,
                metadata_changed_ns = excluded.metadata_changed_ns,
                media_date = excluded.media_date,
                date_source = excluded.date_source,
                processing_state = excluded.processing_state,
                updated_at_ns = excluded.updated_at_ns
            """,
            (
                snapshot.source_path,
                snapshot.sha1,
                snapshot.size_bytes,
                snapshot.modified_ns,
                snapshot.metadata_changed_ns,
                media_date,
                date_source,
                processing_state,
                snapshot.updated_at_ns,
                snapshot.updated_at_ns,
            ),
        )

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        """Create the schema and reject unsupported future versions."""
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS media_files (
                    id INTEGER PRIMARY KEY,
                    source_path TEXT NOT NULL UNIQUE,
                    sha1 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                    modified_ns INTEGER NOT NULL,
                    metadata_changed_ns INTEGER NOT NULL,
                    media_date TEXT,
                    date_source TEXT,
                    processing_state TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_files_sha1 "
                "ON media_files (sha1)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_files_media_date "
                "ON media_files (media_date)"
            )
            connection.execute(
                """
                INSERT INTO schema_meta (key, value)
                VALUES ('version', ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (str(SCHEMA_VERSION),),
            )

        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            version = row[0] if row is not None else "missing"
            raise CatalogError(f"Unsupported media catalog schema version: {version}")

    def _connection_or_raise(self) -> sqlite3.Connection:
        """Return the open connection or explain how to open the catalog."""
        if self._connection is None:
            raise CatalogError("Media catalog is closed; use it as a context manager")
        return self._connection

    @staticmethod
    def _normalize_lookup_path(path: str | Path) -> str:
        """Normalize a path for a catalog lookup without requiring existence."""
        try:
            return str(Path(path).expanduser().resolve(strict=False))
        except (OSError, RuntimeError) as error:
            raise CatalogError(
                f"Could not normalize media path {path}: {error}"
            ) from error


def calculate_sha1(path: str | Path) -> str:
    """Calculate a file SHA-1 incrementally using bounded memory."""
    digest = hashlib.sha1()
    try:
        with Path(path).open("rb") as media_file:
            for chunk in iter(lambda: media_file.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError as error:
        raise CatalogError(f"Could not hash media file {path}: {error}") from error
    return digest.hexdigest()


def _create_snapshot(path: str | Path) -> _FileSnapshot:
    """Read file metadata and content identity before a catalog write."""
    try:
        resolved_path = Path(path).expanduser().resolve(strict=True)
        stat_result = resolved_path.stat()
        if not resolved_path.is_file():
            raise CatalogError(f"Media path is not a regular file: {resolved_path}")
    except (CatalogError, OSError, RuntimeError) as error:
        if isinstance(error, CatalogError):
            raise
        raise CatalogError(f"Could not inspect media file {path}: {error}") from error

    return _FileSnapshot(
        source_path=str(resolved_path),
        sha1=calculate_sha1(resolved_path),
        size_bytes=stat_result.st_size,
        modified_ns=stat_result.st_mtime_ns,
        metadata_changed_ns=stat_result.st_ctime_ns,
        updated_at_ns=time.time_ns(),
    )


def _row_to_record(row: tuple[object, ...]) -> MediaRecord:
    """Convert a SQLite row into the public record type."""
    return MediaRecord(
        id=int(row[0]),
        source_path=str(row[1]),
        sha1=str(row[2]),
        size_bytes=int(row[3]),
        modified_ns=int(row[4]),
        metadata_changed_ns=int(row[5]),
        media_date=str(row[6]) if row[6] is not None else None,
        date_source=str(row[7]) if row[7] is not None else None,
        processing_state=str(row[8]),
        created_at_ns=int(row[9]),
        updated_at_ns=int(row[10]),
    )
