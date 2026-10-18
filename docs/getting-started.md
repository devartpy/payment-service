[← Требования](project.md) · [К README](../README.md) · [Архитектура →](architecture.md)

# Запуск и разработка

Инструкции выполняются из корня этого репозитория. Сейчас запускается HTTP-каркас и PostgreSQL; платёжные маршруты, consumer и RabbitMQ ещё не подключены.

## Требования

| Инструмент | Для чего нужен |
| --- | --- |
| Python 3.10+ | Локальный запуск; Dockerfile и CI используют Python 3.10. |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Установка зависимостей по `uv.lock`. |
| Docker Desktop с Compose | Контейнеры API и PostgreSQL. |
| PowerShell | Команды ниже приведены для Windows. |

`uv.lock` уже входит в репозиторий. При изменении зависимостей обновите его командой `uv lock` и сохраняйте вместе с `pyproject.toml`.

## Локальный запуск API

1. Создайте конфигурацию и замените учебный пароль `DB_PASSWORD=change-me` в `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Создайте окружение и установите зависимости из lock-файла:

   ```powershell
   uv sync --python 3.10 --locked
   ```

3. Запустите приложение:

   ```powershell
   uv run --locked uvicorn src.api.main:app --reload
   ```

4. Откройте `http://127.0.0.1:8000/docs` или проверьте доступность схемы:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/openapi.json | Select-Object -ExpandProperty StatusCode
   ```

   Ожидаемый код — `200`. Список платежных операций в OpenAPI пока пуст: маршрутизатор `src/api/main_router.py` ещё не подключает бизнес-маршруты. Остановите Uvicorn клавишами `Ctrl+C`.

## Запуск через Docker Compose

После настройки `.env` выполните:

```powershell
docker compose up -d --build --wait
docker compose ps
```

Compose поднимает `api` и `db` и ждёт готовности PostgreSQL перед запуском API. Swagger UI доступен на `http://127.0.0.1:8000/docs`. Для остановки без удаления данных:

```powershell
docker compose down
```

В Compose пока нет RabbitMQ, consumer и outbox publisher. Контейнер API пока не открывает подключение к БД при старте; готовность PostgreSQL проверяется отдельно.

Пока используйте `DB_PORT=5432`: текущий Compose не разделяет порт PostgreSQL на хосте и порт подключения внутри контейнера. Причина описана в [переменных окружения](environment-variables.md).

## Проверки

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

CI выполняет эти проверки для pull request. На Windows с GNU Make доступны `make lint`, `make test`, `make up`, `make down` и другие цели из `Makefile`.

## Миграции

`alembic/env.py` импортирует ORM-модели из `src/modules/*/infrastructure/db/models.py`. В платёжном модуле таблиц пока нет; Alembic запрещает `--autogenerate`, пока не появится хотя бы одна модель. После добавления моделей и запуска PostgreSQL:

```powershell
uv run --locked alembic revision --autogenerate -m "create_payment_tables"
uv run --locked alembic upgrade head
```

Перед применением прочитайте `upgrade()` и `downgrade()` новой ревизии. Команды Alembic используют переменные `DB_*` из окружения или `.env`; локальный адрес БД по умолчанию — `localhost:5432`. Миграции выполняются отдельным шагом, а не при старте API.

## See Also

- [Требования](project.md) — что предстоит реализовать.
- [Архитектура](architecture.md) — структура и правила зависимостей.
- [Переменные окружения](environment-variables.md) — значения конфигурации.
