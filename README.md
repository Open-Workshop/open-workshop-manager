# open-workshop-manager

## Layout

Application code now lives under `src/open_workshop_manager`, which makes the package installable in editable mode and keeps imports explicit.

The app now runs on Granian instead of Gunicorn/Uvicorn, so the startup path is a single ASGI server stack.

`ow_config.py` is still supported as a legacy local config file, but environment variables are the preferred way to configure a fresh setup.

Google OAuth credentials are loaded lazily from `credentials.json` in the repo root by default. Set `GOOGLE_OAUTH_CREDENTIALS_PATH` if you keep that file elsewhere.

## Install

```bash
python -m pip install -e .
```

## Run

```bash
granian --interface asgi --host 127.0.0.1 --port 7776 --workers 2 open_workshop_manager.main:app
# or
open-workshop-manager
# or
python -m open_workshop_manager
```

You can also use the helper scripts:

```bash
./start.sh
start.bat
```

## Tools

### Register user (password auth)
Create a new account with a password hash directly in the database.

```bash
python scripts/register_user.py <username>
python scripts/register_user.py <username> --password "secret123"
python scripts/register_user.py <username> --admin

python scripts/change_password.py <username>
python scripts/change_password.py <username> --password "new-secret"
```

These scripts read DB settings through the package settings layer, which still understands `ow_config.py` for compatibility.
The password change tool updates the stored bcrypt hash and invalidates the user's active sessions.

## Uptrace telemetry

Сервер отправляет трейсы в Uptrace через OpenTelemetry, если задан `UPTRACE_DSN`.

Пример запуска:

```bash
export UPTRACE_DSN="https://<token>@api.uptrace.dev/<project_id>"
export OTEL_SERVICE_NAME="open-workshop-manager"
export OTEL_SERVICE_VERSION="1.0.0"
export OTEL_DEPLOYMENT_ENVIRONMENT="production"
# export UPTRACE_OTLP_PROTOCOL="grpc"   # or "http"
# export UPTRACE_FASTAPI_EXCLUDED_URLS="^.*/docs$,^.*/openapi\\.json$,^/favicon\\.ico$,^/robots\\.txt$"
# export UPTRACE_FASTAPI_EXCLUDE_SPANS="receive,send"
python -m open_workshop_manager
```

Опционально можно переопределить OTLP endpoint:

```bash
export UPTRACE_OTLP_TRACES_URL="https://api.uptrace.dev/v1/traces"
# export UPTRACE_OTLP_GRPC_URL="https://api.uptrace.dev:4317"
```
