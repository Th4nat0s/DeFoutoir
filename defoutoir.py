"""Run DeFoutoir directly from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_DIRECTORY = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_DIRECTORY))
__path__ = [str(SOURCE_DIRECTORY / "defoutoir")]
__version__ = "0.1.2"
__license__ = "AGPL-3.0-or-later"

if __name__ == "__main__":
    # pylint: disable=wrong-import-position,import-error,no-name-in-module
    from defoutoir.cli import main  # noqa: E402

    raise SystemExit(main())
