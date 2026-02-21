# Migration Scripts

Исполняемые миграционные скрипты лежат отдельно от обычных утилит в `migration_scripts/`.

Скрипты работают напрямую с БД manager и отдельно делают `HEAD` в storage.

## Переменные окружения

- `OW_STORAGE_URL` — базовый URL storage (пример: `https://storage.openworkshop.miskler.ru`)

## Скрипты

1. `backfill_mods_size_unpacked.py`
- Ищет моды с `mods.size_unpacked IS NULL`.
- Делает `HEAD /download/archive/mods/{mod_id}/main.zip`.
- Берет размер из `X-Unpacked-Bytes`.
- Обновляет `mods.size_unpacked`.

2. `backfill_resources_size.py`
- Ищет ресурсы с `resources.size IS NULL`.
- Для `url LIKE 'local/%'` делает `HEAD /download/resource/{path}`.
- Берет `Content-Length`.
- Обновляет `resources.size`.

## Примеры

```bash
python3 migration_scripts/backfill_mods_size_unpacked.py --concurrency 300
python3 migration_scripts/backfill_resources_size.py --concurrency 300
```

Пробный прогон без записи:

```bash
python3 migration_scripts/backfill_mods_size_unpacked.py --dry-run
python3 migration_scripts/backfill_resources_size.py --dry-run
```
