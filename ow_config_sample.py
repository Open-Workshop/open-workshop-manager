yandex_client_id = "..."
yandex_client_secret = "..."

STORAGE_URL = "http://127.0.0.1:7070"
MAIN_URL = "/api/accounts"
API_BASE_URL = "https://api.openworkshop.miskler.ru"
ACCESS_SERVICE_URL = "http://127.0.0.1:7777"
ACCESS_CALLBACK_TOKEN = ""
ACCESS_TIMEOUT_SECONDS = 30
TRANSFER_JWT_SECRET = ""
TRANSFER_JWT_TTL_SECONDS = 900
STORAGE_TIMEOUT_SECONDS = 1800

# NATS JetStream events for mod add/change/delete.
# Disabled by default; set NATS_URLS or NATS_MOD_EVENTS_ENABLED = True.
NATS_URLS = []
NATS_MOD_EVENTS_ENABLED = False
NATS_MOD_EVENTS_REQUIRED = False
NATS_MOD_EVENTS_STREAM = "MOD_EVENTS"
NATS_MOD_EVENTS_SUBJECT_PREFIX = "mods"
NATS_CONNECT_TIMEOUT_SECONDS = 2
NATS_PUBLISH_TIMEOUT_SECONDS = 2


# MySQL параметры

password_sql = "password"
user_sql = "user"
url_sql = "localhost"
port_sql = 3306


# Хеши токенов


# Access service


# Trusted callback from access service to manager.
# Can be a plain secret or a bcrypt hash, the runtime accepts both.


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
# UPTRACE_FASTAPI_EXCLUDE_SPANS = "receive,send"  # hide noisy ASGI internal spans
# UPTRACE_OTLP_TRACES_URL = "https://api.uptrace.dev/v1/traces"
# UPTRACE_OTLP_GRPC_URL = "https://api.uptrace.dev:4317"
