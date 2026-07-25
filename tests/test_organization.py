"""Tests for deterministic media organization plans."""

# pylint: disable=missing-function-docstring

from pathlib import Path
import hashlib

import pytest

from defoutoir.catalog import MediaRecord
from defoutoir.organization import PlanAction, build_organization_plan


def _record(path: Path, sha1: str, media_date: str | None = None) -> MediaRecord:
    """Create the smallest useful catalog record for a planning test."""
    return MediaRecord(
        id=1,
        source_path=str(path),
        sha1=sha1,
        size_bytes=path.stat().st_size,
        modified_ns=0,
        metadata_changed_ns=0,
        media_date=media_date,
        date_source="test" if media_date else None,
        processing_state="discovered",
        created_at_ns=0,
        updated_at_ns=0,
    )


def test_build_plan_uses_canonical_date_layout_without_creating_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input" / "photo.jpg"
    source.parent.mkdir()
    source.write_bytes(b"photo")
    output = tmp_path / "sorted"

    plan = build_organization_plan(
        (_record(source, "a" * 40, "2024-02-03T12:00:00"),), output
    )

    assert plan.entries[0].destination_path == output / "2024/02/03/photo.jpg"
    assert plan.entries[0].action is PlanAction.COPY
    assert not output.exists()


def test_unknown_date_uses_unknown_directory(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"photo")

    plan = build_organization_plan((_record(source, "a" * 40),), tmp_path / "sorted")

    assert plan.entries[0].destination_path == tmp_path / "sorted/unknown/photo.jpg"


def test_different_content_gets_deterministic_alternate_name(tmp_path: Path) -> None:
    first = tmp_path / "first" / "photo.jpg"
    second = tmp_path / "second" / "photo.jpg"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    records = (_record(first, "1" * 40), _record(second, "2" * 40))

    plan = build_organization_plan(records, tmp_path / "sorted")
    repeated = build_organization_plan(records, tmp_path / "sorted")

    assert plan.entries[0].destination_path == tmp_path / "sorted/unknown/photo.jpg"
    assert plan.entries[1].destination_path == (
        tmp_path / "sorted/unknown/photo__22222222.jpg"
    )
    assert plan.entries == repeated.entries


def test_duplicate_content_is_explicitly_skipped(tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second" / "first.jpg"
    second.parent.mkdir()
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    same_hash = hashlib.sha1(b"same", usedforsecurity=False).hexdigest()
    records = (_record(first, same_hash), _record(second, same_hash))

    plan = build_organization_plan(records, tmp_path / "sorted")

    assert [entry.action for entry in plan.entries] == [
        PlanAction.COPY,
        PlanAction.DUPLICATE,
    ]
    assert plan.summary == {"copy": 1, "duplicate": 1}


def test_existing_same_content_is_duplicate(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"same")
    destination = tmp_path / "sorted" / "unknown"
    destination.mkdir(parents=True)
    (destination / source.name).write_bytes(b"same")

    same_hash = hashlib.sha1(b"same", usedforsecurity=False).hexdigest()
    plan = build_organization_plan((_record(source, same_hash),), tmp_path / "sorted")

    assert plan.entries[0].action is PlanAction.DUPLICATE
    assert plan.entries[0].destination_path == destination / source.name


def test_traversal_candidate_becomes_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        "defoutoir.organization._date_directory", lambda _date: Path("../escape")
    )

    plan = build_organization_plan((_record(source, "a" * 40),), tmp_path / "sorted")

    assert plan.entries[0].action is PlanAction.ERROR
    assert plan.entries[0].destination_path is None
