"""Tests for safe organization plan execution."""

# pylint: disable=missing-function-docstring,protected-access

import hashlib
from pathlib import Path

import pytest

from defoutoir import executor
from defoutoir.catalog import MediaCatalog
from defoutoir.executor import execute_organization_plan
from defoutoir.organization import build_organization_plan


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


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
