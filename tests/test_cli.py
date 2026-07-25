"""Tests for the initial DeFoutoir command-line interface."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from defoutoir.catalog import MediaCatalog
from defoutoir import __license__, __version__
from defoutoir.cli import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_script_help() -> None:
    """The root script must expose help without package installation."""
    environment = os.environ.copy()

    result = subprocess.run(
        [sys.executable, "defoutoir.py", "--help"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Clean and sort pictures and movies by date." in result.stdout


def test_version_is_available() -> None:
    """The package must publish its version."""
    assert __version__ == "0.1.2"
    assert __license__ == "AGPL-3.0-or-later"


def test_main_learn_reports_summary(tmp_path: Path, capsys) -> None:
    """A learn command must catalog inputs and print a clear summary."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()
    (input_directory / "photo.jpg").write_bytes(b"photo")

    assert (
        main(
            [
                "--input",
                str(input_directory),
                "--learn",
                "--database",
                str(tmp_path / "catalog.sqlite3"),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "Learn complete" in captured.err


def test_main_accepts_repeated_inputs_and_copies_files(tmp_path: Path) -> None:
    """Repeated inputs must reach the workflow and produce an organized copy."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    output = tmp_path / "output"
    first.mkdir()
    second.mkdir()
    (first / "one_20240102.jpg").write_bytes(b"one")
    (second / "two_20240103.jpg").write_bytes(b"two")

    result = main(
        [
            "--input",
            str(first),
            "--input",
            str(second),
            "--output",
            str(output),
            "--database",
            str(tmp_path / "catalog.sqlite3"),
        ]
    )

    assert result == 0
    assert (output / "2024/01/02/one_20240102.jpg").read_bytes() == b"one"
    assert (output / "2024/01/03/two_20240103.jpg").read_bytes() == b"two"


def test_main_rejects_missing_output_without_processing(tmp_path: Path, capsys) -> None:
    """Organization mode must explain that an output is required."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()

    assert main(["--input", str(input_directory)]) == 2
    assert "--output is required" in capsys.readouterr().err


def test_main_rejects_input_output_overlap(tmp_path: Path, capsys) -> None:
    """An output inside an input tree must be rejected before scanning."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()

    assert (
        main(
            [
                "--input",
                str(input_directory),
                "--output",
                str(input_directory / "sorted"),
            ]
        )
        == 2
    )
    assert "must not overlap" in capsys.readouterr().err


def test_main_rejects_missing_input_directory(tmp_path: Path, capsys) -> None:
    """A missing input must fail before the catalog is opened."""
    missing = tmp_path / "missing"

    assert main(["--input", str(missing), "--learn"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_main_rejects_incompatible_learn_options(tmp_path: Path, capsys) -> None:
    """Learn mode must remain catalog-only."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()

    assert main(["--input", str(input_directory), "--learn", "--move"]) == 2
    assert "cannot be combined" in capsys.readouterr().err
    assert main(["--input", str(input_directory), "--learn", "--dry-run"]) == 2


def test_main_dry_run_does_not_create_output(tmp_path: Path, capsys) -> None:
    """Dry-run must build the workflow without creating destination files."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()
    (input_directory / "photo_20240102.jpg").write_bytes(b"photo")
    output = tmp_path / "output"

    assert (
        main(["--input", str(input_directory), "--output", str(output), "--dry-run"])
        == 0
    )
    assert not output.exists()
    assert not (tmp_path / "defoutoir.sqlite3").exists()
    assert "DRY-RUN copy" in capsys.readouterr().err


def test_dry_run_move_preserves_source_and_database(tmp_path: Path) -> None:
    """Dry-run move previews operations without persistent mutations."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()
    source = input_directory / "photo_20240102.jpg"
    unknown = input_directory / "unknown.jpg"
    source.write_bytes(b"photo")
    unknown.write_bytes(b"unknown")
    output = tmp_path / "output"
    database = tmp_path / "catalog.sqlite3"

    assert (
        main(
            [
                "--input",
                str(input_directory),
                "--output",
                str(output),
                "--move",
                "--dry-run",
                "--database",
                str(database),
            ]
        )
        == 0
    )

    assert source.read_bytes() == b"photo"
    assert not output.exists()
    assert not database.exists()


def test_dry_run_does_not_change_existing_database(tmp_path: Path) -> None:
    """An existing persistent catalog must remain byte-for-byte unchanged."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()
    (input_directory / "photo.jpg").write_bytes(b"photo")
    database = tmp_path / "catalog.sqlite3"
    assert (
        main(["--input", str(input_directory), "--learn", "--database", str(database)])
        == 0
    )
    before = database.read_bytes()

    assert (
        main(
            [
                "--input",
                str(input_directory),
                "--output",
                str(tmp_path / "output"),
                "--dry-run",
                "--database",
                str(database),
            ]
        )
        == 0
    )

    assert database.read_bytes() == before


def test_main_without_input_returns_validation_error(capsys) -> None:
    """A processing command must explain that input is required."""
    assert main([]) == 2
    assert "--input is required" in capsys.readouterr().err


def test_list_prints_name_hash_date_and_source(tmp_path: Path, capsys) -> None:
    """List mode must read the catalog without requiring input paths."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()
    source = input_directory / "photo_20240102.jpg"
    unknown = input_directory / "unknown.jpg"
    source.write_bytes(b"photo")
    unknown.write_bytes(b"unknown")
    database = tmp_path / "catalog.sqlite3"
    assert (
        main(["--input", str(input_directory), "--learn", "--database", str(database)])
        == 0
    )
    capsys.readouterr()

    assert main(["--list", "--database", str(database)]) == 0
    output = capsys.readouterr().out
    assert "timestamp\tdate_source\tname\tsha1\tpathname" in output
    assert "photo_20240102.jpg" in output
    assert "2024-01-02 00:00:00" in output
    assert "filename.compact_yyyymmdd" in output
    assert str(source) in output

    assert main(["--list-no-date", "--database", str(database)]) == 0
    no_date_output = capsys.readouterr().out
    assert "unknown.jpg" in no_date_output
    assert "photo_20240102.jpg" not in no_date_output

    with MediaCatalog(database) as catalog:
        catalog.update_processing_state(source, "error")
    assert main(["--list-errors", "--database", str(database)]) == 0
    errors_output = capsys.readouterr().out
    assert "photo_20240102.jpg" in errors_output
    assert "unknown.jpg" not in errors_output


def test_list_missing_database_is_validation_error(tmp_path: Path, capsys) -> None:
    """List mode must not create a missing catalog database."""
    database = tmp_path / "missing.sqlite3"

    assert main(["--list", "--database", str(database)]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not database.exists()
