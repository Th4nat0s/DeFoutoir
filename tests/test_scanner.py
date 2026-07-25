"""Tests for recursive media discovery."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from defoutoir.scanner import (
    MEDIA_EXTENSIONS,
    MOVIE_EXTENSIONS,
    PICTURE_EXTENSIONS,
    discover_media,
    is_supported_media,
)

MEDIA_FIXTURES = Path(__file__).parent / "fixtures" / "media"


def create_file(path: Path, content: bytes = b"fixture") -> Path:
    """Create a small test file and return its resolved path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path.resolve()


def test_discovers_supported_media_recursively(tmp_path: Path) -> None:
    """A single input must include supported files in nested directories."""
    expected = {
        create_file(tmp_path / "photo.JPG"),
        create_file(tmp_path / "nested" / "movie.MP4"),
        create_file(tmp_path / "nested" / "camera.nef"),
    }
    create_file(tmp_path / "notes.txt")

    result = discover_media([tmp_path])

    assert set(result.media_files) == expected
    assert result.input_directories == 1
    assert result.scanned_directories == 2
    assert result.scanned_files == 4
    assert result.skipped_paths == 1
    assert result.warning_count == 0


def test_discovers_media_from_multiple_inputs(tmp_path: Path) -> None:
    """Several independent inputs must contribute to one result."""
    first_input = tmp_path / "phone"
    second_input = tmp_path / "camera"
    expected = (
        create_file(second_input / "a.png"),
        create_file(first_input / "b.mov"),
    )

    result = discover_media([first_input, second_input])

    assert set(result.media_files) == set(expected)
    assert result.input_directories == 2


def test_overlapping_and_duplicate_inputs_are_scanned_once(tmp_path: Path) -> None:
    """Nested and repeated inputs must not duplicate discovered paths."""
    nested_input = tmp_path / "media" / "nested"
    media_file = create_file(nested_input / "photo.jpg")
    parent_input = tmp_path / "media"

    result = discover_media([nested_input, parent_input, parent_input])

    assert result.media_files == (media_file,)
    assert result.input_directories == 1
    assert result.skipped_paths == 2


def test_failed_inputs_do_not_block_valid_inputs(tmp_path: Path) -> None:
    """A missing input must produce a warning while valid inputs continue."""
    valid_input = tmp_path / "valid"
    media_file = create_file(valid_input / "photo.webp")

    result = discover_media([tmp_path / "missing", valid_input])

    assert result.media_files == (media_file,)
    assert result.warning_count == 1
    assert result.skipped_paths == 1


def test_file_input_is_rejected(tmp_path: Path) -> None:
    """Inputs must be directories rather than individual media files."""
    media_file = create_file(tmp_path / "photo.jpg")

    result = discover_media([media_file])

    assert result.media_files == ()
    assert result.input_directories == 0
    assert result.warning_count == 1


def test_unreadable_directory_does_not_abort_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable nested directory must not hide other valid media."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    valid_file = create_file(tmp_path / "valid.jpg")
    original_iterdir = Path.iterdir

    def guarded_iterdir(path: Path):
        if path == blocked:
            raise PermissionError("test directory is unreadable")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)

    result = discover_media([tmp_path])

    assert result.media_files == (valid_file,)
    assert result.warning_count == 1
    assert result.skipped_paths == 1


def test_symbolic_links_are_skipped(tmp_path: Path) -> None:
    """File and directory symlinks must not be followed or duplicated."""
    media_file = create_file(tmp_path / "original.jpg")
    nested_file = create_file(tmp_path / "nested" / "movie.mp4")
    (tmp_path / "linked-file.jpg").symlink_to(media_file)
    (tmp_path / "linked-directory").symlink_to(
        tmp_path / "nested",
        target_is_directory=True,
    )

    result = discover_media([tmp_path])

    assert set(result.media_files) == {media_file, nested_file}
    assert result.skipped_paths == 2


def test_macos_metadata_directories_are_skipped(tmp_path: Path) -> None:
    """AppleDouble and macOS archive metadata must not be treated as media."""
    valid_file = create_file(tmp_path / "photo.jpg")
    create_file(tmp_path / ".AppleDouble" / "0713.jpg", b"resource fork")
    create_file(tmp_path / "__MACOSX" / "preview.png", b"resource fork")

    result = discover_media([tmp_path])

    assert result.media_files == (valid_file,)
    assert result.skipped_paths == 2


def test_results_are_deterministic(tmp_path: Path) -> None:
    """Repeated discovery must return exactly the same ordered paths."""
    create_file(tmp_path / "z.jpg")
    create_file(tmp_path / "A.png")
    create_file(tmp_path / "nested" / "m.mov")

    first_result = discover_media([tmp_path])
    second_result = discover_media([tmp_path])

    assert first_result.media_files == second_result.media_files
    assert first_result.media_files == tuple(
        sorted(
            first_result.media_files,
            key=lambda path: (path.as_posix().casefold(), path.as_posix()),
        )
    )


def test_all_downloaded_media_fixtures_are_supported() -> None:
    """The ten downloaded fixtures must all be discoverable media."""
    result = discover_media([MEDIA_FIXTURES])

    assert len(result.media_files) == 10
    assert all(is_supported_media(path) for path in result.media_files)


def test_supported_extensions_are_documented_categories() -> None:
    """Picture and movie sets must be non-empty, normalized, and distinct."""
    assert PICTURE_EXTENSIONS
    assert MOVIE_EXTENSIONS
    assert PICTURE_EXTENSIONS.isdisjoint(MOVIE_EXTENSIONS)
    assert MEDIA_EXTENSIONS == PICTURE_EXTENSIONS | MOVIE_EXTENSIONS
    assert all(extension.startswith(".") for extension in MEDIA_EXTENSIONS)
    assert all(extension == extension.casefold() for extension in MEDIA_EXTENSIONS)


def test_discovery_logs_progress_skips_and_summary(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Discovery must provide clear operational log messages."""
    create_file(tmp_path / "photo.jpg")
    create_file(tmp_path / "ignored.txt")
    logger = logging.getLogger("tests.discovery")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        discover_media([tmp_path], logger=logger)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("Scanning input directory:") for message in messages)
    assert any(message.startswith("Discovered media file:") for message in messages)
    assert any(message.startswith("Skipping unsupported file:") for message in messages)
    assert any(message.startswith("Discovery complete:") for message in messages)
