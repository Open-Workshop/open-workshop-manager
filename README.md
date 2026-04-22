# open-workshop-manager

Backend сервиса OpenWorkshop.Manager.
Это ASGI-приложение для аккаунтов, игр, модов, ресурсов, тегов, ассоциаций и
служебных админских операций.

## Что важно знать

- Код лежит в `src/open_workshop_manager`, проект использует `src`-layout.
- Сервер запускается через Granian.
- SQL-слой переведён на async SQLAlchemy + `aiomysql`.
- Ответы и ошибки оформляются через Pydantic-модели и единый слой стандартов.
- Для локальной разработки есть отдельные `make`-цели, скрипты и совместимый
  legacy-конфиг.

## Структура проекта

- `src/open_workshop_manager` - основной пакет приложения
- `scripts` - админские утилиты
- `migration_scripts` - вспомогательные скрипты для данных
- `main.py` - compatibility shim для старого способа запуска
- `start.sh` / `start.bat` - готовые сценарии запуска

## Требования

- Python 3.11 или новее
- MySQL / MariaDB
- Доступ к сервису хранения файлов
- При необходимости:
  - Google OAuth credentials
  - Yandex OAuth credentials
  - Uptrace для трассировки

## Установка

### Обычная установка

```bash
python -m pip install -e .
```

### Установка для разработки

```bash
python -m pip install -e '.[dev]'
# или
python -m pip install -r requirements-dev.txt
```

## Запуск

### Через пакетный entrypoint

```bash
python -m open_workshop_manager
```

### Через установленную команду

```bash
open-workshop-manager
```

### Через helper-скрипты

```bash
./start.sh
start.bat
```

По умолчанию сервер слушает `127.0.0.1:7776`.

Можно переопределить:

- `OPEN_WORKSHOP_MANAGER_HOST`
- `OPEN_WORKSHOP_MANAGER_PORT`
- `OPEN_WORKSHOP_MANAGER_WORKERS`
- `OPEN_WORKSHOP_MANAGER_ACCESS_LOG`

## Конфигурация

Проект читает настройки из переменных окружения.
Если переменная не задана, поддерживается legacy-файл `ow_config.py`.
Для нового развёртывания лучше использовать именно env-переменные.

### Сервер

- `OPEN_WORKSHOP_MANAGER_HOST` - адрес Granian
- `OPEN_WORKSHOP_MANAGER_PORT` - порт Granian
- `OPEN_WORKSHOP_MANAGER_WORKERS` - число воркеров
- `OPEN_WORKSHOP_MANAGER_ACCESS_LOG` - включать ли access log

### База данных

- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`

Для старых конфигов также понимаются:

- `url_sql`
- `port_sql`
- `user_sql`
- `password_sql`

### Базовые URL и токены

- `MAIN_URL` - базовый префикс API, по умолчанию `/api/accounts`
- `STORAGE_URL` - адрес storage-сервиса
- `API_BASE_URL` - внешний базовый URL приложения
- `ACCESS_SERVICE_URL` - адрес сервиса расчёта прав
- `ACCESS_SERVICE_TOKEN` - токен manager -> access
- `ACCESS_CALLBACK_TOKEN` - доверенный токен access -> manager для fallback callback
- `ACCESS_TIMEOUT_SECONDS` - таймаут запросов к access-сервису
- `TRANSFER_JWT_SECRET` - секрет для transfer JWT
- `TRANSFER_JWT_TTL_SECONDS` - TTL для transfer JWT
- `STORAGE_TIMEOUT_SECONDS` - таймаут запросов к storage

### OAuth и куки

- `YANDEX_CLIENT_ID`
- `YANDEX_CLIENT_SECRET`
- `GOOGLE_OAUTH_CREDENTIALS_PATH` - путь к JSON с Google OAuth credentials
- `COOKIE_DOMAIN`
- `COOKIE_SAMESITE`
- `COOKIE_SECURE`

По умолчанию Google credentials читаются из `credentials.json` в корне
репозитория, если путь не переопределён.

### Токены для storage

- `STORAGE_UPLOAD_TOKEN`
- `STORAGE_DELETE_TOKEN`
- `STORAGE_MANAGE_TOKEN`

### Токены для access

- `ACCESS_SERVICE_TOKEN`
- `ACCESS_CALLBACK_TOKEN`

`ACCESS_CALLBACK_TOKEN` используется доверенным callback-роутом между
access-сервисом и manager. Его можно хранить как обычный секрет или как
bcrypt-хэш.

### CORS

- `CORS_ORIGINS`
- `ALLOW_LOCALHOST_CORS`
- `LOCALHOST_CORS_ORIGINS`

### Телеметрия

- `UPTRACE_DSN`
- `OTEL_SERVICE_NAME`
- `OTEL_SERVICE_VERSION`
- `OTEL_DEPLOYMENT_ENVIRONMENT`
- `UPTRACE_OTLP_PROTOCOL`
- `UPTRACE_OTLP_TRACES_URL`
- `UPTRACE_OTLP_GRPC_URL`
- `UPTRACE_FASTAPI_EXCLUDED_URLS`
- `UPTRACE_FASTAPI_EXCLUDE_SPANS`

## Документация API

После запуска доступны стандартные страницы FastAPI:

- `/docs`
- `/redoc`
- `/openapi.json`

## Скрипты

### Создание пользователя

```bash
python scripts/register_user.py <username>
python scripts/register_user.py <username> --password "secret123"
python scripts/register_user.py <username> --admin
```

### Смена пароля

```bash
python scripts/change_password.py <username>
python scripts/change_password.py <username> --password "new-secret"
```

`change_password.py` обновляет bcrypt-хэш пароля и инвалидирует активные
сессии пользователя.

## Команды для разработки

```bash
make format
make lint
make type-check
```

- `format` - `isort` + `black`
- `lint` - `flake8` + `isort --check-only`
- `type-check` - `mypy`

## База данных

При старте приложение создаёт отсутствующие таблицы через SQLAlchemy metadata.
Это удобно для пустого окружения, но не заменяет полноценные миграции.

## Телеметрия Uptrace

Если задать `UPTRACE_DSN`, приложение начнёт отправлять трейсы в Uptrace.

Пример запуска:

```bash
export UPTRACE_DSN="https://<token>@api.uptrace.dev/<project_id>"
export OTEL_SERVICE_NAME="open-workshop-manager"
export OTEL_SERVICE_VERSION="1.0.0"
export OTEL_DEPLOYMENT_ENVIRONMENT="production"
# export UPTRACE_OTLP_PROTOCOL="grpc"   # или "http"
# export UPTRACE_FASTAPI_EXCLUDED_URLS="^.*/docs$,^.*/openapi\\.json$,^/favicon\\.ico$,^/robots\\.txt$"
# export UPTRACE_FASTAPI_EXCLUDE_SPANS="receive,send"
python -m open_workshop_manager
```

Можно также переопределить OTLP endpoint:

```bash
export UPTRACE_OTLP_TRACES_URL="https://api.uptrace.dev/v1/traces"
# export UPTRACE_OTLP_GRPC_URL="https://api.uptrace.dev:4317"
```

## Примечание по совместимости

`ow_config.py` поддерживается для старых локальных установок, но новый формат
конфигурации лучше держать через переменные окружения.
