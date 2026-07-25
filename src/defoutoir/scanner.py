"""Read-only discovery of media files in input directories."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from defoutoir.log import get_logger

PICTURE_EXTENSIONS = frozenset(
    {
        ".arw",
        ".bmp",
        ".cr2",
        ".cr3",
        ".dng",
        ".gif",
        ".heic",
        ".heif",
        ".jpeg",
        ".jpg",
        ".nef",
        ".nrw",
        ".orf",
        ".pef",
        ".png",
        ".raf",
        ".raw",
        ".rw2",
        ".sr2",
        ".srf",
        ".tif",
        ".tiff",
        ".webp",
        ".x3f",
    }
)
MOVIE_EXTENSIONS = frozenset(
    {
        ".3g2",
        ".3gp",
        ".avi",
        ".m2ts",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mts",
        ".webm",
        ".wmv",
    }
)
MEDIA_EXTENSIONS = PICTURE_EXTENSIONS | MOVIE_EXTENSIONS
IGNORED_DIRECTORY_NAMES = frozenset({".appledouble", "__macosx"})


class DiscoveryResult(NamedTuple):
    """Summary and ordered media files produced by discovery."""

    media_files: tuple[Path, ...]
    input_directories: int
    scanned_directories: int
    scanned_files: int
    skipped_paths: int
    warning_count: int


class _InputSelection(NamedTuple):
    """Normalized roots and counters produced during input validation."""

    roots: tuple[Path, ...]
    skipped_paths: int
    warning_count: int


def is_supported_media(path: Path) -> bool:
    """Return whether a path has a supported media extension."""
    return path.suffix.casefold() in MEDIA_EXTENSIONS


def discover_media(
    input_directories: Iterable[str | Path],
    logger: logging.Logger | None = None,
) -> DiscoveryResult:
    """Discover supported media recursively in one or more input directories."""
    active_logger = logger or get_logger("scanner")
    selection = _select_input_roots(input_directories, active_logger)
    media_files: set[Path] = set()
    scanned_directories = 0
    scanned_files = 0
    skipped_paths = selection.skipped_paths
    warning_count = selection.warning_count

    for root in selection.roots:
        active_logger.info("Scanning input directory: %s", root)
        root_result = _scan_root(root, active_logger)
        media_files.update(root_result.media_files)
        scanned_directories += root_result.scanned_directories
        scanned_files += root_result.scanned_files
        skipped_paths += root_result.skipped_paths
        warning_count += root_result.warning_count

    ordered_files = tuple(sorted(media_files, key=_path_sort_key))
    active_logger.info(
        "Discovery complete: %d media files from %d inputs; "
        "%d directories scanned, %d files inspected, %d paths skipped, "
        "%d warnings.",
        len(ordered_files),
        len(selection.roots),
        scanned_directories,
        scanned_files,
        skipped_paths,
        warning_count,
    )
    return DiscoveryResult(
        media_files=ordered_files,
        input_directories=len(selection.roots),
        scanned_directories=scanned_directories,
        scanned_files=scanned_files,
        skipped_paths=skipped_paths,
        warning_count=warning_count,
    )


def _select_input_roots(
    input_directories: Iterable[str | Path],
    logger: logging.Logger,
) -> _InputSelection:
    """Resolve, validate, sort, and de-duplicate input directories."""
    valid_roots: set[Path] = set()
    skipped_paths = 0
    warning_count = 0

    for input_directory in input_directories:
        candidate = Path(input_directory).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            logger.warning("Cannot read input path %s: %s", candidate, error)
            skipped_paths += 1
            warning_count += 1
            continue

        if not resolved.is_dir():
            logger.warning("Input path is not a directory: %s", resolved)
            skipped_paths += 1
            warning_count += 1
            continue

        if resolved in valid_roots:
            logger.info("Skipping duplicate input directory: %s", resolved)
            skipped_paths += 1
            continue

        valid_roots.add(resolved)

    selected_roots: list[Path] = []
    for root in sorted(valid_roots, key=_path_sort_key):
        if any(root.is_relative_to(parent) for parent in selected_roots):
            logger.info("Skipping overlapping input directory: %s", root)
            skipped_paths += 1
            continue
        selected_roots.append(root)

    return _InputSelection(
        roots=tuple(selected_roots),
        skipped_paths=skipped_paths,
        warning_count=warning_count,
    )


def _scan_root(root: Path, logger: logging.Logger) -> DiscoveryResult:
    """Scan one validated root without following symbolic links."""
    pending_directories = [root]
    media_files: set[Path] = set()
    scanned_directories = 0
    scanned_files = 0
    skipped_paths = 0
    warning_count = 0

    while pending_directories:
        directory = pending_directories.pop()
        scanned_directories += 1
        logger.debug("Scanning directory: %s", directory)
        try:
            children = sorted(directory.iterdir(), key=_path_sort_key)
        except OSError as error:
            logger.warning("Cannot scan directory %s: %s", directory, error)
            skipped_paths += 1
            warning_count += 1
            continue

        child_directories: list[Path] = []
        for child in children:
            if child.is_symlink():
                logger.debug("Skipping symbolic link: %s", child)
                skipped_paths += 1
                continue

            try:
                if child.is_dir():
                    if child.name.casefold() in IGNORED_DIRECTORY_NAMES:
                        logger.debug("Skipping metadata directory: %s", child)
                        skipped_paths += 1
                        continue
                    child_directories.append(child)
                    continue
                if not child.is_file():
                    logger.debug("Skipping non-file path: %s", child)
                    skipped_paths += 1
                    continue
            except OSError as error:
                logger.warning("Cannot inspect path %s: %s", child, error)
                skipped_paths += 1
                warning_count += 1
                continue

            scanned_files += 1
            if is_supported_media(child):
                media_files.add(child)
                logger.debug("Discovered media file: %s", child)
            else:
                logger.debug("Skipping unsupported file: %s", child)
                skipped_paths += 1

        pending_directories.extend(reversed(child_directories))

    return DiscoveryResult(
        media_files=tuple(sorted(media_files, key=_path_sort_key)),
        input_directories=1,
        scanned_directories=scanned_directories,
        scanned_files=scanned_files,
        skipped_paths=skipped_paths,
        warning_count=warning_count,
    )


def _path_sort_key(path: Path) -> tuple[str, str]:
    """Return a stable, case-insensitive path sort key."""
    normalized_path = path.as_posix()
    return normalized_path.casefold(), normalized_path
