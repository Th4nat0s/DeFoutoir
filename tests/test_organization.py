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


def test_unicode_equivalent_names_share_one_normalized_destination(
    tmp_path: Path,
) -> None:
    """NFD and NFC names must not create two visually identical share paths."""
    first = tmp_path / "first" / "Moyeuvre-Grande-à.JPG"
    second = tmp_path / "second" / "Moyeuvre-Grande-a\u0300.JPG"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    same_hash = hashlib.sha1(b"same", usedforsecurity=False).hexdigest()

    plan = build_organization_plan(
        (_record(first, same_hash), _record(second, same_hash)),
        tmp_path / "sorted",
    )

    destinations = {entry.destination_path for entry in plan.entries}
    assert destinations == {tmp_path / "sorted/unknown/Moyeuvre-Grande-à.JPG"}
    assert plan.summary == {"copy": 1, "duplicate": 1}


def test_unicode_equivalent_names_with_different_content_use_alternate_name(
    tmp_path: Path,
) -> None:
    """Normalization collisions must preserve both different files safely."""
    first = tmp_path / "first" / "Moyeuvre-Grande-à.JPG"
    second = tmp_path / "second" / "Moyeuvre-Grande-a\u0300.JPG"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    records = (_record(first, "1" * 40), _record(second, "2" * 40))

    plan = build_organization_plan(records, tmp_path / "sorted")

    destination_names = {
        entry.destination_path.name
        for entry in plan.entries
        if entry.destination_path is not None
    }
    assert destination_names == {
        "Moyeuvre-Grande-à.JPG",
        "Moyeuvre-Grande-à__22222222.JPG",
    }


def test_duplicate_group_prefers_shortest_name_containing_a_date(
    tmp_path: Path,
) -> None:
    """A dated canonical name wins before an unrelated shorter name."""
    sources = [
        tmp_path / "toto.jpg",
        tmp_path / "IMG_20161203_143236-2.jpg",
        tmp_path / "IMG_20161203_143236.jpg",
    ]
    for source in sources:
        source.write_bytes(b"same")
    same_hash = hashlib.sha1(b"same", usedforsecurity=False).hexdigest()

    plan = build_organization_plan(
        tuple(_record(source, same_hash, "2016-12-03 14:32:38") for source in sources),
        tmp_path / "sorted",
    )

    assert plan.entries[0].source_path.name == "IMG_20161203_143236.jpg"
    assert plan.entries[0].action is PlanAction.COPY
    assert plan.summary == {"copy": 1, "duplicate": 2}


def test_existing_output_content_suppresses_copy_under_another_name(
    tmp_path: Path,
) -> None:
    """Output-wide content identity must not depend on a destination filename."""
    source = tmp_path / "source.jpg"
    source.write_bytes(b"same")
    same_hash = hashlib.sha1(b"same", usedforsecurity=False).hexdigest()
    existing = tmp_path / "sorted/unknown/already-there.jpg"

    plan = build_organization_plan(
        (_record(source, same_hash),),
        tmp_path / "sorted",
        existing_content={same_hash: existing},
    )

    assert plan.entries[0].action is PlanAction.DUPLICATE
    assert plan.entries[0].destination_path == existing


def test_plan_orders_undated_then_oldest_to_newest(tmp_path: Path) -> None:
    """Execution order must make chronological progress visible to users."""
    newest = tmp_path / "newest.jpg"
    unknown = tmp_path / "unknown.jpg"
    oldest = tmp_path / "oldest.jpg"
    newest.write_bytes(b"newest")
    unknown.write_bytes(b"unknown")
    oldest.write_bytes(b"oldest")
    records = (
        _record(newest, "3" * 40, "2024-06-03 09:00:00"),
        _record(unknown, "2" * 40),
        _record(oldest, "1" * 40, "1999-01-02 08:00:00"),
    )

    plan = build_organization_plan(records, tmp_path / "sorted")

    assert [entry.source_path.name for entry in plan.entries] == [
        "unknown.jpg",
        "oldest.jpg",
        "newest.jpg",
    ]


def test_equal_timestamps_use_stable_path_order(tmp_path: Path) -> None:
    """Equal dates must retain a deterministic cross-run order."""
    second = tmp_path / "z.jpg"
    first = tmp_path / "A.jpg"
    second.write_bytes(b"second")
    first.write_bytes(b"first")
    records = (
        _record(second, "2" * 40, "2024-01-02 12:00:00"),
        _record(first, "1" * 40, "2024-01-02 12:00:00"),
    )

    plan = build_organization_plan(records, tmp_path / "sorted")

    assert [entry.source_path.name for entry in plan.entries] == ["A.jpg", "z.jpg"]


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
