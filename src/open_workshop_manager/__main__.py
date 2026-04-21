"""Module entrypoint for `python -m open_workshop_manager`."""

from __future__ import annotations

import os

from granian import Granian
from granian.constants import Interfaces
from granian.log import LogLevels

from open_workshop_manager import settings as config


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_log_level(value: str | None) -> LogLevels:
    if not value:
        return LogLevels.info
    try:
        return LogLevels(value.strip().lower())
    except ValueError:
        return LogLevels.info


def main() -> None:
    host = os.getenv("OPEN_WORKSHOP_MANAGER_HOST", "127.0.0.1")
    port = _read_int_env("OPEN_WORKSHOP_MANAGER_PORT", 7776)
    workers = _read_int_env("OPEN_WORKSHOP_MANAGER_WORKERS", 2)
    access_log = _read_bool_env("OPEN_WORKSHOP_MANAGER_ACCESS_LOG", False)
    log_level = _resolve_log_level(getattr(config, "LOG_LEVEL", None))

    Granian(
        "open_workshop_manager.main:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        workers=workers,
        log_level=log_level,
        log_access=access_log,
        process_name="open-workshop-manager",
    ).serve()


if __name__ == "__main__":
    main()
