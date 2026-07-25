"""Tests for the initial DeFoutoir command-line interface."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from defoutoir import __version__
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


def test_main_reports_ready_status(capsys) -> None:
    """A normal command run must print a clear status message."""
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "INFO: DeFoutoir is ready." in captured.err
