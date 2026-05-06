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

- Python 3.10 или новее
- MySQL / MariaDB
- Доступ к сервису хранения файлов
- При необходимости:
  - NATS Server с JetStream для событий модов
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

- `STORAGE_URL` - адрес storage-сервиса
- `API_BASE_URL` - внешний базовый URL приложения
- `ACCESS_SERVICE_URL` - адрес сервиса расчёта прав
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

- `ACCESS_CALLBACK_TOKEN`

`ACCESS_CALLBACK_TOKEN` используется доверенным callback-роутом между
access-сервисом и manager. Его можно хранить как обычный секрет или как
bcrypt-хэш.

### NATS JetStream events

Manager умеет публиковать события жизненного цикла модов в NATS JetStream,
чтобы зависимые сервисы, например `open-workshop-website`, могли вести свой
локальный индекс без обходного чтения таблиц manager.

Публикуемые subjects:

- `mods.added`
- `mods.changed`
- `mods.deleted`
- `mods.rated`

Stream по умолчанию: `MOD_EVENTS`. Если stream отсутствует, manager создаёт
его при старте с перечисленными subjects.

Payload каждого события:

```json
{
  "event": "mod.changed",
  "id": 123,
  "title": "Mod title",
  "full_description": "Full mod description",
  "public": 0,
  "occurred_at": "2026-04-25T12:30:00+00:00"
}
```

Поля `id`, `title`, `full_description`, `public` передаются всегда. Значение
`public` совпадает с полем мода в catalog: `0` - публичный и индексируемый,
`1` - доступен по ссылке, `2` - непубличный. Для удаления используется тот же
payload, но `event` будет `mod.deleted`. При голосовании за мод публикуется
`mods.rated`, а в payload дополнительно приходят `vote_value`, `rating`,
`votes_count` и `voter_id`.

Настройки:

- `NATS_URLS` - список адресов NATS, например `["nats://127.0.0.1:4222"]`
- `NATS_MOD_EVENTS_ENABLED` - включает публикацию событий; по умолчанию
  включается автоматически, если задан `NATS_URLS`
- `NATS_MOD_EVENTS_REQUIRED` - если `True`, ошибки подключения или публикации
  считаются критичными и пробрасываются наружу
- `NATS_MOD_EVENTS_STREAM` - имя JetStream stream, по умолчанию `MOD_EVENTS`
- `NATS_MOD_EVENTS_SUBJECT_PREFIX` - prefix subjects, по умолчанию `mods`
- `NATS_CONNECT_TIMEOUT_SECONDS` - таймаут подключения, по умолчанию `2`
- `NATS_PUBLISH_TIMEOUT_SECONDS` - таймаут публикации, по умолчанию `2`

Минимальная конфигурация:

```bash
export NATS_URLS='["nats://127.0.0.1:4222"]'
```

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

## Философия API

Текущий HTTP API специально приведён к единому контракту и дальше развивается
как ломающийся интерфейс без версионирования и без legacy-совместимости.

- Ресурсы живут в обычном REST-контуре: `GET`, `POST`, `PATCH`, `DELETE` для
  сущностей вроде `games`, `genres`, `tags`, `mods`, `resources`,
  `profiles/{user_id}`.
- Действия и workflow живут в command/RPC-контуре: `uploads`, `sessions`,
  `oauth`, `internal`.
- `GET` не должен менять состояние системы. Любые счётчики, записи событий,
  токены, transfer-workflow и похожие эффекты выносятся в `POST`/`PATCH`/`DELETE`.
- Создание ресурса возвращает `201 Created` и JSON созданного объекта.
- Обновление ресурса возвращает `200 OK` и JSON обновлённого объекта.
- Удаление ресурса возвращает `204 No Content`.
- Списки возвращаются в формате `{ "items": [...], "pagination": {...} }`.
- Ошибки возвращаются в `application/problem+json` с полями
  `title`, `status`, `detail`, `instance`, `code`.
- Параметры фильтрации, сортировки и include-режимы задаются через query
  string; массивы передаются повторяющимися параметрами, а не JSON в path.

Ключевая идея: API не обязан быть "чистым REST", но он обязан быть честно
разделённым. Ресурсные endpoint'ы выглядят как ресурсные, command endpoint'ы
выглядят как команды, и оба слоя не маскируют друг друга.

## Рейтинги

- `PUT /mods/{mod_id}/rating` - поставить, изменить или снять голос за мод.
- `PUT /modpacks/{modpack_id}/rating` - поставить, изменить или снять голос за модпак.
- `PUT /profiles/{user_id}/rating` - поставить, изменить или снять голос за профиль.
- `GET /profiles/{user_id}/rating/history` - посмотреть историю голосов пользователя.
- `rating` у модов и модпаков хранится как процент одобрения, а `votes_count` показывает число активных голосов.
- `PUT /profiles/{user_id}/rating` возвращает `rating` как процент одобрения и `votes_count` с числом активных голосов для отдельной оценки профиля.
- `GET /profiles/{user_id}` в `general` возвращает `rating` и `votes_count`, рассчитанные по голосам за моды и модпаки автора.
- В каталоге моды можно сортировать по `rating` через `sort=rating` или `sort=-rating`.
- Голосование доступно только авторизованным пользователям с правом `vote_for_reputation` в Access.

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
