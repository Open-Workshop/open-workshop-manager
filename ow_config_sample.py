yandex_client_id = "..."
yandex_client_secret = "..."

STORAGE_URL = "http://127.0.0.1:7070"
MAIN_URL = "/api/accounts"
TRANSFER_JWT_SECRET = ""
TRANSFER_JWT_TTL_SECONDS = 900
STORAGE_TIMEOUT_SECONDS = 1800


# MySQL параметры

password_sql = "password"
user_sql = "user"
url_sql = "localhost"
port_sql = 3306


# Хеши токенов


# Доступ к не публичным модам

access_mods_check_anonymous = ""


# Storage

storage_upload_token = ""
storage_delete_token = ""
storage_manage_token = ""


# Cookies / CORS

# For localhost set COOKIE_DOMAIN = "" (or None) and COOKIE_SECURE = False
COOKIE_DOMAIN = ".openworkshop.miskler.ru"
COOKIE_SAMESITE = "Lax"  # "Lax" | "Strict" | "None"
COOKIE_SECURE = True

CORS_ORIGINS = [
    "https://openworkshop.miskler.ru",
    "https://api.openworkshop.miskler.ru",
]

# Allow localhost for dev frontends talking to prod API
ALLOW_LOCALHOST_CORS = True
LOCALHOST_CORS_ORIGINS = [
    "http://localhost:6660",
    "http://127.0.0.1:6660",
]


# Optional telemetry settings (recommended to set via environment variables)
# UPTRACE_DSN = "https://<token>@api.uptrace.dev/<project_id>"
# OTEL_SERVICE_NAME = "open-workshop-manager"
# OTEL_SERVICE_VERSION = "1.0.0"
# OTEL_DEPLOYMENT_ENVIRONMENT = "production"
# UPTRACE_OTLP_PROTOCOL = "grpc"  # or "http"
# UPTRACE_FASTAPI_EXCLUDED_URLS = "^.*/docs$,^.*/openapi\\.json$,^/favicon\\.ico$,^/robots\\.txt$"
# UPTRACE_OTLP_TRACES_URL = "https://api.uptrace.dev/v1/traces"
# UPTRACE_OTLP_GRPC_URL = "https://api.uptrace.dev:4317"
