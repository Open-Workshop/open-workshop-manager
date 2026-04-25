"""Runtime settings with environment and legacy config support."""

from __future__ import annotations

import importlib
import json
import os
from types import ModuleType
from typing import Literal, cast
from urllib.parse import quote

try:
    _LEGACY_CONFIG: ModuleType | None = importlib.import_module("ow_config")
except ModuleNotFoundError:  # pragma: no cover - legacy config is optional
    _LEGACY_CONFIG = None


def _read(name: str, default: object = None, legacy_name: str | None = None) -> object:
    if name in os.environ:
        return os.environ[name]

    if legacy_name and _LEGACY_CONFIG is not None and hasattr(_LEGACY_CONFIG, legacy_name):
        return getattr(_LEGACY_CONFIG, legacy_name)

    if _LEGACY_CONFIG is not None and hasattr(_LEGACY_CONFIG, name):
        return getattr(_LEGACY_CONFIG, name)

    return default


def _read_str(name: str, default: str = "", legacy_name: str | None = None) -> str:
    value = _read(name=name, default=default, legacy_name=legacy_name)
    if value is None:
        return default
    return str(value)


def _read_int(name: str, default: int, legacy_name: str | None = None) -> int:
    value = _read(name=name, default=default, legacy_name=legacy_name)
    try:
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(value)
    except (TypeError, ValueError):
        pass
    return default


def _read_bool(name: str, default: bool, legacy_name: str | None = None) -> bool:
    value = _read(name=name, default=default, legacy_name=legacy_name)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _read_list(name: str, default: list[str], legacy_name: str | None = None) -> list[str]:
    value = _read(name=name, default=default, legacy_name=legacy_name)
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(parsed, list):
            return parsed
        return [str(parsed)]
    return list(default)


yandex_client_id = _read_str("YANDEX_CLIENT_ID", "", "yandex_client_id")
yandex_client_secret = _read_str("YANDEX_CLIENT_SECRET", "", "yandex_client_secret")

STORAGE_URL = _read_str("STORAGE_URL", "http://127.0.0.1:7070")
MAIN_URL = _read_str("MAIN_URL", "/api/accounts")
API_BASE_URL = _read_str("API_BASE_URL", "https://api.openworkshop.miskler.ru")
ACCESS_SERVICE_URL = _read_str("ACCESS_SERVICE_URL", "http://127.0.0.1:7777")
ACCESS_CALLBACK_TOKEN = _read_str("ACCESS_CALLBACK_TOKEN", "", "access_callback_token")
ACCESS_TIMEOUT_SECONDS = _read_int("ACCESS_TIMEOUT_SECONDS", 30)
TRANSFER_JWT_SECRET = _read_str("TRANSFER_JWT_SECRET", "")
TRANSFER_JWT_TTL_SECONDS = _read_int("TRANSFER_JWT_TTL_SECONDS", 900)
STORAGE_TIMEOUT_SECONDS = _read_int("STORAGE_TIMEOUT_SECONDS", 1800)

NATS_URLS = _read_list("NATS_URLS", [])
NATS_MOD_EVENTS_ENABLED = _read_bool(
    "NATS_MOD_EVENTS_ENABLED",
    bool(NATS_URLS),
)
NATS_MOD_EVENTS_REQUIRED = _read_bool("NATS_MOD_EVENTS_REQUIRED", False)
NATS_MOD_EVENTS_STREAM = _read_str("NATS_MOD_EVENTS_STREAM", "MOD_EVENTS")
NATS_MOD_EVENTS_SUBJECT_PREFIX = _read_str(
    "NATS_MOD_EVENTS_SUBJECT_PREFIX",
    "mods",
)
NATS_CONNECT_TIMEOUT_SECONDS = _read_int("NATS_CONNECT_TIMEOUT_SECONDS", 2)
NATS_PUBLISH_TIMEOUT_SECONDS = _read_int("NATS_PUBLISH_TIMEOUT_SECONDS", 2)

password_sql = _read_str("PASSWORD_SQL", "password", "password_sql")
user_sql = _read_str("USER_SQL", "user", "user_sql")
url_sql = _read_str("URL_SQL", "localhost", "url_sql")
port_sql = _read_int("PORT_SQL", 3306, "port_sql")

MYSQL_PASSWORD = password_sql
MYSQL_USER = user_sql
MYSQL_HOST = url_sql
MYSQL_PORT = port_sql


def mysql_url(database: str) -> str:
    safe_database = quote(database, safe="")
    if MYSQL_USER and MYSQL_PASSWORD:
        safe_user = quote(MYSQL_USER, safe="")
        safe_password = quote(MYSQL_PASSWORD, safe="")
        auth = f"{safe_user}:{safe_password}@"
    elif MYSQL_USER:
        safe_user = quote(MYSQL_USER, safe="")
        auth = f"{safe_user}@"
    else:
        auth = ""
    return f"mysql+aiomysql://{auth}{MYSQL_HOST}:{MYSQL_PORT}/{safe_database}"


access_mods_check_anonymous = _read_str(
    "ACCESS_MODS_CHECK_ANONYMOUS", "", "access_mods_check_anonymous"
)

storage_upload_token = _read_str("STORAGE_UPLOAD_TOKEN", "", "storage_upload_token")
storage_delete_token = _read_str("STORAGE_DELETE_TOKEN", "", "storage_delete_token")
storage_manage_token = _read_str("STORAGE_MANAGE_TOKEN", "", "storage_manage_token")

COOKIE_DOMAIN = _read_str("COOKIE_DOMAIN", ".openworkshop.miskler.ru")
SameSite = Literal["lax", "strict", "none"]


def _read_samesite(name: str, default: SameSite = "lax") -> SameSite:
    value = _read_str(name, default).strip().lower()
    if value in {"lax", "strict", "none"}:
        return cast(SameSite, value)
    return default


COOKIE_SAMESITE: SameSite = _read_samesite("COOKIE_SAMESITE", "lax")
COOKIE_SECURE = _read_bool("COOKIE_SECURE", True)

CORS_ORIGINS = _read_list(
    "CORS_ORIGINS",
    [
        "https://openworkshop.miskler.ru",
        "https://api.openworkshop.miskler.ru",
    ],
)
ALLOW_LOCALHOST_CORS = _read_bool("ALLOW_LOCALHOST_CORS", True)
LOCALHOST_CORS_ORIGINS = _read_list(
    "LOCALHOST_CORS_ORIGINS",
    [
        "http://localhost:6660",
        "http://127.0.0.1:6660",
    ],
)

LOG_LEVEL = _read_str("LOG_LEVEL", "DEBUG")

UPTRACE_DSN = _read_str("UPTRACE_DSN", "")
OTEL_SERVICE_NAME = _read_str("OTEL_SERVICE_NAME", "open-workshop-manager")
OTEL_SERVICE_VERSION = _read_str("OTEL_SERVICE_VERSION", "dev")
OTEL_DEPLOYMENT_ENVIRONMENT = _read_str(
    "OTEL_DEPLOYMENT_ENVIRONMENT", "production"
)
UPTRACE_OTLP_PROTOCOL = _read_str("UPTRACE_OTLP_PROTOCOL", "")
UPTRACE_FASTAPI_EXCLUDED_URLS = _read_str(
    "UPTRACE_FASTAPI_EXCLUDED_URLS",
    r"^.*/docs$,^.*/openapi\.json$,^/favicon\.ico$,^/robots\.txt$",
)
UPTRACE_FASTAPI_EXCLUDE_SPANS = _read_str(
    "UPTRACE_FASTAPI_EXCLUDE_SPANS", "receive,send"
)
UPTRACE_OTLP_TRACES_URL = _read_str("UPTRACE_OTLP_TRACES_URL", "")
UPTRACE_OTLP_GRPC_URL = _read_str("UPTRACE_OTLP_GRPC_URL", "")
