"""Run DeFoutoir directly from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_DIRECTORY = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_DIRECTORY))

# pylint: disable=wrong-import-position,import-error,no-name-in-module
from defoutoir.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
