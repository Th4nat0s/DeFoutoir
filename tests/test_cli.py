"""Tests for the initial DeFoutoir command-line interface."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from defoutoir import __license__, __version__
from defoutoir.cli import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_module_help() -> None:
    """The package must expose help through python -m defoutoir."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "defoutoir", "--help"],
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
    assert __version__ == "0.1.0"
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


def test_main_dry_run_does_not_create_output(tmp_path: Path) -> None:
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


def test_main_without_input_uses_argparse_validation() -> None:
    """Argparse must retain its standard validation exit code."""
    with pytest.raises(SystemExit) as error:
        main([])

    assert error.value.code == 2
