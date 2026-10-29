"""Tests for safe organization plan execution."""

# pylint: disable=missing-function-docstring,protected-access

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from defoutoir import executor
from defoutoir.catalog import MediaCatalog
from defoutoir.executor import execute_organization_plan
from defoutoir.organization import build_organization_plan
from defoutoir.metadata import extract_media_date


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


@pytest.mark.parametrize("extension", ("jpg", "png"))
def test_exif_copy_writes_only_one_destination_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    """NAS EXIF copies must stream directly without rewriting a staged copy."""
    source = tmp_path / f"source.{extension}"
    destination = tmp_path / "output" / source.name
    Image.new("RGB", (8, 6), color="blue").save(source)
    original_bytes = source.read_bytes()
    original_temporary = executor.tempfile.NamedTemporaryFile
    temporaries = []

    def track_temporary(*args, **kwargs):
        # The executor owns and closes this returned temporary file.
        # pylint: disable=consider-using-with
        result = original_temporary(*args, **kwargs)
        temporaries.append(result.name)
        return result

    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", track_temporary)
    executor._copy_exclusive(source, destination, datetime(2024, 1, 2, 12))

    assert len(temporaries) == 1
    assert source.read_bytes() == original_bytes
    assert extract_media_date(destination).value == datetime(2024, 1, 2, 12)
    with Image.open(source) as first, Image.open(destination) as second:
        assert first.tobytes() == second.tobytes()


def test_streaming_exif_copy_keeps_existing_date(tmp_path: Path) -> None:
    """Stale catalog fallback dates must never overwrite real source metadata."""
    source = tmp_path / "source.jpg"
    destination = tmp_path / "output/source.jpg"
    exif = Image.Exif()
    exif[36867] = "2001:02:03 04:05:06"
    Image.new("RGB", (8, 6)).save(source, exif=exif)

    executor._copy_exclusive(source, destination, datetime(2024, 1, 2, 12))

    assert destination.read_bytes() == source.read_bytes()


def test_interrupted_exif_stream_does_not_publish_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streaming failures must keep the source and remove partial output."""
    source = tmp_path / "source.jpg"
    destination = tmp_path / "output/source.jpg"
    source.write_bytes(b"source")

    def failing_chunks(*_args, **_kwargs):
        yield b"partial"
        raise OSError("interrupted stream")

    monkeypatch.setattr(executor, "iter_copy_chunks", failing_chunks)
    with pytest.raises(OSError, match="interrupted stream"):
        executor._copy_exclusive(source, destination, datetime(2024, 1, 2, 12))

    assert source.read_bytes() == b"source"
    assert not destination.exists()
    assert not tuple(destination.parent.iterdir())


def test_copy_creates_destination_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    content = b"copy me"
    source.write_bytes(content)
    with MediaCatalog(":memory:") as catalog:
        record = catalog.record_file(source, "2024-01-02", "test")
        plan = build_organization_plan((record,), tmp_path / "sorted")
        result = execute_organization_plan(plan, catalog)

        assert result.summary == {"copy": 1}
        assert source.read_bytes() == content
        assert plan.entries[0].destination_path is not None
        assert plan.entries[0].destination_path.read_bytes() == content
        assert catalog.get_by_path(source).processing_state == "copied"


def test_journal_and_copy_are_interleaved_per_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Large plans must start copying before later entries are journaled."""
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    events: list[tuple[str, str]] = []

    with MediaCatalog(":memory:") as catalog:
        records = (catalog.record_file(first), catalog.record_file(second))
        plan = build_organization_plan(records, tmp_path / "sorted")
        original_prepare = catalog.prepare_operation
        original_copy = executor._copy_plan_entry

        def track_prepare(source, destination, operation, sha1):
            events.append(("journal", Path(source).name))
            return original_prepare(source, destination, operation, sha1)

        def track_copy(entry, logger):
            events.append(("copy", entry.source_path.name))
            return original_copy(entry, logger)

        monkeypatch.setattr(catalog, "prepare_operation", track_prepare)
        monkeypatch.setattr(executor, "_copy_plan_entry", track_copy)
        execute_organization_plan(plan, catalog)

    assert events == [
        ("journal", "first.jpg"),
        ("copy", "first.jpg"),
        ("journal", "second.jpg"),
        ("copy", "second.jpg"),
    ]


def test_move_removes_source_only_after_success(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"move me")
    with MediaCatalog(":memory:") as catalog:
        record = catalog.record_file(source, "2024-01-02", "test")
        plan = build_organization_plan((record,), tmp_path / "sorted", "move")
        result = execute_organization_plan(plan, catalog)

        assert result.summary == {"move": 1}
        assert not source.exists()
        assert plan.entries[0].destination_path is not None
        assert plan.entries[0].destination_path.exists()
        assert catalog.get_by_path(source).processing_state == "moved"


def test_failed_move_keeps_source_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    with MediaCatalog(":memory:") as catalog:
        first_record = catalog.record_file(first)
        second_record = catalog.record_file(second)
        plan = build_organization_plan(
            (first_record, second_record), tmp_path / "sorted", "move"
        )
        original_copy = executor._copy_exclusive
        calls = {"count": 0}

        def fail_second(source: Path, destination: Path) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated interruption")
            original_copy(source, destination)

        monkeypatch.setattr("defoutoir.executor._copy_exclusive", fail_second)
        result = execute_organization_plan(plan, catalog)

        assert result.summary == {"error": 1, "move": 1}
        assert not first.exists()
        assert second.exists()
        assert catalog.get_by_path(second).processing_state == "error"


def test_rerunning_completed_move_is_duplicate(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    content = b"repeat"
    source.write_bytes(content)
    with MediaCatalog(":memory:") as catalog:
        record = catalog.record_file(source, "2024-01-02", "test")
        plan = build_organization_plan((record,), tmp_path / "sorted", "move")
        execute_organization_plan(plan, catalog)

        repeated_plan = build_organization_plan((record,), tmp_path / "sorted", "move")
        repeated = execute_organization_plan(repeated_plan, catalog)

        assert repeated.summary == {"duplicate": 1}
        assert repeated_plan.entries[0].destination_path.read_bytes() == content


def test_existing_different_content_is_never_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"new")
    output = tmp_path / "sorted" / "unknown"
    output.mkdir(parents=True)
    existing = output / source.name
    existing.write_bytes(b"old")
    with MediaCatalog(":memory:") as catalog:
        record = catalog.record_file(source)
        record = record._replace(sha1=_sha1(b"new"))
        plan = build_organization_plan((record,), tmp_path / "sorted")
        result = execute_organization_plan(plan, catalog)

        assert result.summary == {"copy": 1}
        assert existing.read_bytes() == b"old"
        assert plan.entries[0].destination_path != existing


def test_interrupted_move_resumes_after_destination_was_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restart must finish a move interrupted before source deletion."""
    source = tmp_path / "source.jpg"
    source.write_bytes(b"resume move")
    database = tmp_path / "catalog.sqlite3"
    output = tmp_path / "sorted"

    with MediaCatalog(database) as catalog:
        record = catalog.record_file(source, "2024-01-02", "test")
        plan = build_organization_plan((record,), output, "move")
        original_update = catalog.update_operation

        def interrupt_after_copy(*args, **kwargs):
            if args[4] == "copied":
                raise KeyboardInterrupt
            return original_update(*args, **kwargs)

        monkeypatch.setattr(catalog, "update_operation", interrupt_after_copy)
        with pytest.raises(KeyboardInterrupt):
            execute_organization_plan(plan, catalog)

    destination = output / "2024/01/02/source.jpg"
    assert destination.read_bytes() == b"resume move"
    assert source.exists()

    with MediaCatalog(database) as catalog:
        record = catalog.get_by_path(source)
        assert record is not None
        repeated_plan = build_organization_plan((record,), output, "move")
        result = execute_organization_plan(repeated_plan, catalog)
        journal = catalog.get_operation(
            source, destination, "move", _sha1(b"resume move")
        )

    assert result.summary == {"move": 1}
    assert not source.exists()
    assert journal is not None
    assert journal.status == "completed"


def test_copy_publishes_only_one_canonical_file_per_source_hash(
    tmp_path: Path,
) -> None:
    """Different source names with identical content must produce one copy."""
    sources = [
        tmp_path / "IMG_20161203_143236-2.jpg",
        tmp_path / "IMG_20161203_143236-3.jpg",
        tmp_path / "IMG_20161203_143236.jpg",
    ]
    for source in sources:
        source.write_bytes(b"same")
    with MediaCatalog(":memory:") as catalog:
        records = tuple(catalog.record_file(source) for source in sources)
        plan = build_organization_plan(records, tmp_path / "sorted")
        result = execute_organization_plan(plan, catalog)

    assert result.summary == {"copy": 1, "duplicate": 2}
    assert [path.name for path in (tmp_path / "sorted/unknown").iterdir()] == [
        "IMG_20161203_143236.jpg"
    ]
    assert all(source.exists() for source in sources)


def test_move_deletes_every_source_after_one_canonical_publish(tmp_path: Path) -> None:
    """A successful grouped move must clean all selected duplicate sources."""
    sources = [
        tmp_path / "IMG_20161203_143236-2.jpg",
        tmp_path / "IMG_20161203_143236-3.jpg",
        tmp_path / "IMG_20161203_143236.jpg",
    ]
    for source in sources:
        source.write_bytes(b"same")
    with MediaCatalog(":memory:") as catalog:
        records = tuple(catalog.record_file(source) for source in sources)
        plan = build_organization_plan(records, tmp_path / "sorted", "move")
        result = execute_organization_plan(plan, catalog)

    assert result.summary == {"move": 3}
    assert not any(source.exists() for source in sources)
    assert [path.name for path in (tmp_path / "sorted/unknown").iterdir()] == [
        "IMG_20161203_143236.jpg"
    ]


def test_interrupted_duplicate_cleanup_resumes_without_recopying(  # pylint: disable=too-many-locals
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Grouped move cleanup must resume at the first remaining source."""
    sources = [
        tmp_path / "IMG_20161203_143236-2.jpg",
        tmp_path / "IMG_20161203_143236-3.jpg",
        tmp_path / "IMG_20161203_143236.jpg",
    ]
    for source in sources:
        source.write_bytes(b"same")
    database = tmp_path / "catalog.sqlite3"
    output = tmp_path / "sorted"
    source_set = set(sources)
    original_unlink = Path.unlink
    deletions = {"count": 0}

    def interrupt_second_source(path: Path, *args, **kwargs):
        if path in source_set:
            deletions["count"] += 1
            if deletions["count"] == 2:
                raise KeyboardInterrupt
        return original_unlink(path, *args, **kwargs)

    with MediaCatalog(database) as catalog:
        records = tuple(catalog.record_file(source) for source in sources)
        plan = build_organization_plan(records, output, "move")
        monkeypatch.setattr(Path, "unlink", interrupt_second_source)
        with pytest.raises(KeyboardInterrupt):
            execute_organization_plan(plan, catalog)

    monkeypatch.undo()
    destination = output / "unknown/IMG_20161203_143236.jpg"
    assert destination.read_bytes() == b"same"
    assert sum(source.exists() for source in sources) == 2

    with MediaCatalog(database) as catalog:
        records = tuple(
            record
            for source in sources
            if (record := catalog.get_by_path(source)) is not None
        )
        existing = catalog.index_output(output)
        repeated_plan = build_organization_plan(
            records,
            output,
            "move",
            existing_content=existing,
        )
        result = execute_organization_plan(repeated_plan, catalog)

    assert result.summary == {"duplicate": 1, "move": 2}
    assert not any(source.exists() for source in sources)
    assert tuple(output.rglob("*.jpg")) == (destination,)
