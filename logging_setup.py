from __future__ import annotations

import logging
import os

DEFAULT_LOG_LEVEL = "DEBUG"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s:%(lineno)d - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _normalize_level(value: str | None) -> str:
    if not value:
        return "INFO"
    level = value.strip().upper()
    return level if level in logging._nameToLevel else DEFAULT_LOG_LEVEL


def _resolve_log_level() -> str:
    env_level = os.getenv("LOG_LEVEL")
    if env_level:
        return _normalize_level(env_level)

    try:
        import ow_config as config
    except Exception:
        return DEFAULT_LOG_LEVEL

    return _normalize_level(getattr(config, "LOG_LEVEL", DEFAULT_LOG_LEVEL))


def setup_logging() -> None:
    level = _resolve_log_level()
    log_format = os.getenv("LOG_FORMAT", DEFAULT_LOG_FORMAT)
    date_format = os.getenv("LOG_DATE_FORMAT", DEFAULT_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    logging.basicConfig(level=level, format=log_format, datefmt=date_format)
