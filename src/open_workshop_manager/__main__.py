"""Module entrypoint for `python -m open_workshop_manager`."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("OPEN_WORKSHOP_MANAGER_HOST", "127.0.0.1")
    port_raw = os.getenv("OPEN_WORKSHOP_MANAGER_PORT", "7776")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 7776

    uvicorn.run("open_workshop_manager.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
