"""Compatibility wrapper for the package entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from open_workshop_manager.main import app  # noqa: E402

__all__ = ["app"]


if __name__ == "__main__":
    from open_workshop_manager.__main__ import main as _run_server

    _run_server()
