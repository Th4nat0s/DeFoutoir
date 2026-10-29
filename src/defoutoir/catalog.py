"""SQLite catalog and content identity operations for DeFoutoir."""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from defoutoir.log import get_logger
from defoutoir.scanner import MEDIA_EXTENSIONS

DEFAULT_DATABASE_PATH = Path("defoutoir.sqlite3")
SCHEMA_VERSION = 3
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


class OperationJournalEntry(NamedTuple):
    """A durable copy or move operation that can be resumed."""

    id: int
    source_path: str
    destination_path: str
    operation: str
    sha1: str
    status: str
    error: str | None
    created_at_ns: int
    updated_at_ns: int


class OutputContent(NamedTuple):
    """One indexed media file below a specific organization output."""

    destination_path: str
    source_sha1: str | None
    output_sha1: str
    size_bytes: int
    modified_ns: int
    metadata_changed_ns: int


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
        self._resolved_paths: dict[str, str] = {}
        self._output_ids: dict[str, int] = {}

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
        self._resolved_paths.clear()
        self._output_ids.clear()

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

    def prepare_operation(
        self,
        source: str | Path,
        destination: str | Path,
        operation: str,
        sha1: str,
    ) -> OperationJournalEntry:
        """Create or reset one resumable copy or move journal entry."""
        if operation not in ("copy", "move"):
            raise CatalogError(f"Unsupported journal operation: {operation}")
        source_path = self._normalize_lookup_path(source)
        destination_path = self._normalize_lookup_path(destination)
        now = time.time_ns()
        connection = self._connection_or_raise()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO operation_journal (
                        source_path, destination_path, operation, sha1,
                        status, error, created_at_ns, updated_at_ns
                    ) VALUES (?, ?, ?, ?, 'pending', NULL, ?, ?)
                    ON CONFLICT(source_path, destination_path, operation, sha1)
                    DO UPDATE SET
                        status = 'pending',
                        error = NULL,
                        updated_at_ns = excluded.updated_at_ns
                    """,
                    (
                        source_path,
                        destination_path,
                        operation,
                        sha1,
                        now,
                        now,
                    ),
                )
        except sqlite3.Error as error:
            raise CatalogError(
                f"Could not prepare operation journal: {error}"
            ) from error
        entry = self.get_operation(source, destination, operation, sha1)
        if entry is None:
            raise CatalogError("Operation journal entry disappeared after creation")
        self._logger.info(
            "Journaled %s operation: %s -> %s", operation, source_path, destination_path
        )
        return entry

    def get_operation(
        self,
        source: str | Path,
        destination: str | Path,
        operation: str,
        sha1: str,
    ) -> OperationJournalEntry | None:
        """Return the journal entry matching one exact planned operation."""
        row = (
            self._connection_or_raise()
            .execute(
                """
            SELECT id, source_path, destination_path, operation, sha1,
                   status, error, created_at_ns, updated_at_ns
            FROM operation_journal
            WHERE source_path = ? AND destination_path = ?
              AND operation = ? AND sha1 = ?
            """,
                (
                    self._normalize_lookup_path(source),
                    self._normalize_lookup_path(destination),
                    operation,
                    sha1,
                ),
            )
            .fetchone()
        )
        return _row_to_operation(row) if row is not None else None

    def update_operation(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        source: str | Path,
        destination: str | Path,
        operation: str,
        sha1: str,
        status: str,
        error: str | None = None,
    ) -> OperationJournalEntry:
        """Persist a journal checkpoint for one copy or move operation."""
        if status not in ("pending", "copied", "completed", "error"):
            raise CatalogError(f"Unsupported journal status: {status}")
        source_path = self._normalize_lookup_path(source)
        destination_path = self._normalize_lookup_path(destination)
        connection = self._connection_or_raise()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE operation_journal
                    SET status = ?, error = ?, updated_at_ns = ?
                    WHERE source_path = ? AND destination_path = ?
                      AND operation = ? AND sha1 = ?
                    """,
                    (
                        status,
                        error,
                        time.time_ns(),
                        source_path,
                        destination_path,
                        operation,
                        sha1,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CatalogError(
                        "Operation is not journaled: "
                        f"{source_path} -> {destination_path}"
                    )
        except sqlite3.Error as db_error:
            raise CatalogError(
                f"Could not update operation journal: {db_error}"
            ) from db_error
        entry = self.get_operation(source, destination, operation, sha1)
        if entry is None:
            raise CatalogError("Operation journal entry disappeared after update")
        self._logger.info(
            "Operation journal checkpoint %s: %s -> %s",
            status,
            source_path,
            destination_path,
        )
        return entry

    def index_output(  # pylint: disable=too-many-locals
        self, output: str | Path
    ) -> dict[str, Path]:
        """Incrementally index one output tree and return content locations."""
        output_path = self._normalize_lookup_path(output)
        connection = self._connection_or_raise()
        now = time.time_ns()
        with connection:
            connection.execute(
                """
                INSERT INTO organization_outputs (
                    output_path, created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?)
                ON CONFLICT(output_path) DO UPDATE SET
                    updated_at_ns = excluded.updated_at_ns
                """,
                (output_path, now, now),
            )
        output_id = self._output_id(output_path)
        indexed = {row.destination_path: row for row in self._output_records(output_id)}
        seen: set[str] = set()
        discovered: list[OutputContent] = []
        changed: list[OutputContent] = []
        for path in _iter_output_files(Path(output_path)):
            normalized = self._normalize_lookup_path(path)
            seen.add(normalized)
            details = path.stat()
            previous = indexed.get(normalized)
            if (
                previous is not None
                and previous.size_bytes == details.st_size
                and previous.modified_ns == details.st_mtime_ns
                and previous.metadata_changed_ns == details.st_ctime_ns
            ):
                discovered.append(previous)
                continue
            output_sha1 = calculate_sha1(path)
            source_sha1 = (
                previous.source_sha1
                if previous is not None and previous.output_sha1 == output_sha1
                else None
            )
            record = OutputContent(
                normalized,
                source_sha1,
                output_sha1,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
            )
            changed.append(record)
            discovered.append(record)

        self._upsert_output_records(output_id, changed)
        stale = set(indexed) - seen
        if stale:
            with connection:
                connection.executemany(
                    "DELETE FROM organized_content "
                    "WHERE output_id = ? AND destination_path = ?",
                    ((output_id, path) for path in stale),
                )
        content = _content_locations(discovered)
        self._logger.info(
            "Indexed output %s: %d media file(s), %d unique content hash(es).",
            output_path,
            len(discovered),
            len(content),
        )
        return content

    def record_output_content(
        self,
        output: str | Path,
        destination: str | Path,
        source_sha1: str,
        output_sha1: str,
    ) -> None:
        """Record a successfully published destination in its output index."""
        output_path = self._normalize_lookup_path(output)
        destination_path = Path(self._normalize_lookup_path(destination))
        details = destination_path.stat()
        now = time.time_ns()
        connection = self._connection_or_raise()
        if output_path not in self._output_ids:
            with connection:
                connection.execute(
                    """
                    INSERT INTO organization_outputs (
                        output_path, created_at_ns, updated_at_ns
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(output_path) DO NOTHING
                    """,
                    (output_path, now, now),
                )
        output_id = self._output_id(output_path)
        self._upsert_output_records(
            output_id,
            (
                OutputContent(
                    str(destination_path),
                    source_sha1,
                    output_sha1,
                    details.st_size,
                    details.st_mtime_ns,
                    details.st_ctime_ns,
                ),
            ),
        )

    def _output_id(self, output_path: str) -> int:
        """Return the database identifier for a registered output path."""
        if output_path in self._output_ids:
            return self._output_ids[output_path]
        row = (
            self._connection_or_raise()
            .execute(
                "SELECT id FROM organization_outputs WHERE output_path = ?",
                (output_path,),
            )
            .fetchone()
        )
        if row is None:
            raise CatalogError(f"Organization output is not registered: {output_path}")
        self._output_ids[output_path] = int(row[0])
        return self._output_ids[output_path]

    def _output_records(self, output_id: int) -> tuple[OutputContent, ...]:
        """Return cached files for one output identifier."""
        rows = (
            self._connection_or_raise()
            .execute(
                """
            SELECT destination_path, source_sha1, output_sha1, size_bytes,
                   modified_ns, metadata_changed_ns
            FROM organized_content
            WHERE output_id = ?
            ORDER BY destination_path
            """,
                (output_id,),
            )
            .fetchall()
        )
        return tuple(
            OutputContent(
                str(row[0]),
                str(row[1]) if row[1] is not None else None,
                str(row[2]),
                int(row[3]),
                int(row[4]),
                int(row[5]),
            )
            for row in rows
        )

    def _upsert_output_records(
        self, output_id: int, records: Iterable[OutputContent]
    ) -> None:
        """Insert or refresh cached output files in one transaction."""
        records = tuple(records)
        if not records:
            return
        connection = self._connection_or_raise()
        with connection:
            connection.executemany(
                """
                INSERT INTO organized_content (
                    output_id, destination_path, source_sha1, output_sha1,
                    size_bytes, modified_ns, metadata_changed_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(output_id, destination_path) DO UPDATE SET
                    source_sha1 = excluded.source_sha1,
                    output_sha1 = excluded.output_sha1,
                    size_bytes = excluded.size_bytes,
                    modified_ns = excluded.modified_ns,
                    metadata_changed_ns = excluded.metadata_changed_ns,
                    updated_at_ns = excluded.updated_at_ns
                """,
                (
                    (
                        output_id,
                        record.destination_path,
                        record.source_sha1,
                        record.output_sha1,
                        record.size_bytes,
                        record.modified_ns,
                        record.metadata_changed_ns,
                        time.time_ns(),
                    )
                    for record in records
                ),
            )

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
                media_date = COALESCE(excluded.media_date, media_files.media_date),
                date_source = COALESCE(excluded.date_source, media_files.date_source),
                processing_state = CASE
                    WHEN media_files.sha1 = excluded.sha1
                     AND media_files.size_bytes = excluded.size_bytes
                     AND media_files.modified_ns = excluded.modified_ns
                    THEN media_files.processing_state
                    ELSE excluded.processing_state
                END,
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
        if row is not None and int(row[0]) == 1:
            with connection:
                connection.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'version'",
                    (str(SCHEMA_VERSION),),
                )

        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS operation_journal (
                    id INTEGER PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    destination_path TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK (operation IN ('copy', 'move')),
                    sha1 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'copied', 'completed', 'error')
                    ),
                    error TEXT,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    UNIQUE(source_path, destination_path, operation, sha1)
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operation_journal_status "
                "ON operation_journal (status)"
            )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS organization_outputs (
                    id INTEGER PRIMARY KEY,
                    output_path TEXT NOT NULL UNIQUE,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS organized_content (
                    id INTEGER PRIMARY KEY,
                    output_id INTEGER NOT NULL REFERENCES organization_outputs(id)
                        ON DELETE CASCADE,
                    destination_path TEXT NOT NULL,
                    source_sha1 TEXT,
                    output_sha1 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                    modified_ns INTEGER NOT NULL,
                    metadata_changed_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    UNIQUE(output_id, destination_path)
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_organized_content_output_sha1 "
                "ON organized_content (output_id, output_sha1)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_organized_content_source_sha1 "
                "ON organized_content (output_id, source_sha1)"
            )

        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        if row is not None and int(row[0]) == 2:
            with connection:
                connection.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'version'",
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

    def _normalize_lookup_path(self, path: str | Path) -> str:
        """Resolve each absolute lookup path once per open catalog session."""
        try:
            absolute = str(Path(path).expanduser().absolute())
            if absolute not in self._resolved_paths:
                resolved = str(Path(absolute).resolve(strict=False))
                self._resolved_paths[absolute] = resolved
                self._resolved_paths[resolved] = resolved
            return self._resolved_paths[absolute]
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


def scan_output_content(output: str | Path) -> dict[str, Path]:
    """Build a read-only content map for a dry-run output tree."""
    records = []
    for path in _iter_output_files(Path(output).expanduser().resolve(strict=False)):
        details = path.stat()
        records.append(
            OutputContent(
                str(path.resolve(strict=True)),
                None,
                calculate_sha1(path),
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
            )
        )
    return _content_locations(records)


def _iter_output_files(output: Path) -> Iterable[Path]:
    """Yield supported regular media files without following symlinks."""
    if not output.is_dir():
        return
    for directory, names, filenames in os.walk(
        output,
        followlinks=False,
        onerror=_raise_walk_error,
    ):
        names[:] = sorted(
            name for name in names if not (Path(directory) / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if (
                not path.is_symlink()
                and path.is_file()
                and path.suffix.casefold() in MEDIA_EXTENSIONS
            ):
                yield path


def _raise_walk_error(error: OSError) -> None:
    """Propagate an output traversal error instead of silently skipping it."""
    raise error


def _content_locations(records: Iterable[OutputContent]) -> dict[str, Path]:
    """Select one stable existing location for every output content hash."""
    locations: dict[str, Path] = {}
    for record in sorted(records, key=lambda item: item.destination_path):
        locations.setdefault(record.output_sha1, Path(record.destination_path))
    return locations


def read_catalog_records(database_path: str | Path) -> tuple[MediaRecord, ...]:
    """Read catalog records without creating or changing the SQLite file."""
    path = Path(database_path).expanduser().resolve(strict=False)
    if not path.is_file():
        raise CatalogError(f"Media catalog does not exist: {path}")

    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
        )
        rows = connection.execute("""
            SELECT id, source_path, sha1, size_bytes, modified_ns,
                   metadata_changed_ns, media_date, date_source,
                   processing_state, created_at_ns, updated_at_ns
            FROM media_files
            ORDER BY source_path
            """).fetchall()
    except sqlite3.Error as error:
        raise CatalogError(f"Could not read media catalog {path}: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()
    return tuple(_row_to_record(row) for row in rows)


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


def _row_to_operation(row: tuple[object, ...]) -> OperationJournalEntry:
    """Convert a SQLite row into a public operation journal entry."""
    return OperationJournalEntry(
        id=int(row[0]),
        source_path=str(row[1]),
        destination_path=str(row[2]),
        operation=str(row[3]),
        sha1=str(row[4]),
        status=str(row[5]),
        error=str(row[6]) if row[6] is not None else None,
        created_at_ns=int(row[7]),
        updated_at_ns=int(row[8]),
    )
