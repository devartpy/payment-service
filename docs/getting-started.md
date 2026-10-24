[К README](../README.md) · [REST API →](api.md)

# Запуск и разработка

Инструкции выполняются из корня репозитория. POST/GET платежей работают с PostgreSQL; publisher, consumer и RabbitMQ ещё не подключены.

## Требования

| Инструмент | Для чего нужен |
| --- | --- |
| Python 3.10+ | Локальный запуск; Dockerfile и CI используют Python 3.10. |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Установка зависимостей по `uv.lock`. |
| Docker Desktop с Compose | Контейнеры API и PostgreSQL. |
| PowerShell | Команды ниже приведены для Windows. |

`uv.lock` уже входит в репозиторий. При изменении зависимостей обновите его командой `uv lock` и сохраняйте вместе с `pyproject.toml`.

## Локальный запуск API

1. Создайте конфигурацию, замените учебные `DB_PASSWORD=change-me` и `API_KEY=replace-with-a-secret` в `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Создайте окружение и установите зависимости из lock-файла:

   ```powershell
   uv sync --python 3.10 --locked
   ```

3. Запустите PostgreSQL и примените миграции:

   ```powershell
   docker compose up -d db --wait
   uv run --locked alembic upgrade head
   ```

4. Запустите приложение:

   ```powershell
   uv run --locked uvicorn src.api.main:app --reload
   ```

5. Откройте `http://127.0.0.1:8000/docs` или проверьте доступность схемы:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/openapi.json | Select-Object -ExpandProperty StatusCode
   ```

   Ожидаемый код — `200`. В OpenAPI есть POST и GET платежей. Пример создания и чтения — в [REST API](api.md). Остановите Uvicorn клавишами `Ctrl+C`.

## Запуск через Docker Compose

После настройки `.env` выполните:

```powershell
docker compose up -d --build --wait
docker compose ps
```

Compose поднимает `api` и `db` и ждёт готовности PostgreSQL перед запуском API. Примените миграции отдельной командой с хоста: `uv run --locked alembic upgrade head`. Swagger UI доступен на `http://127.0.0.1:8000/docs`. Для остановки без удаления данных:

```powershell
docker compose down
```

В Compose пока нет RabbitMQ, consumer и outbox publisher. API создаёт фабрику асинхронных сессий при старте и использует БД при платёжных запросах; миграции не запускаются автоматически.

Пока используйте `DB_PORT=5432`: текущий Compose не разделяет порт PostgreSQL на хосте и порт подключения внутри контейнера. Причина описана в [переменных окружения](environment-variables.md).

## Проверки

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

CI выполняет эти проверки для pull request и предварительно применяет миграции. Локальные интеграционные и HTTP-тесты используют запущенную PostgreSQL: каждый создаёт собственную временную схему, применяет к ней миграции и удаляет только эту схему. Отдельная тестовая БД или новый контейнер на каждый тест не нужны. На Windows с GNU Make доступны `make lint`, `make test`, `make up`, `make down` и другие цели из `Makefile`.

## Миграции

`alembic/env.py` импортирует ORM-модели из `src/modules/*/infrastructure/db/models.py`. Модели `payments` и `outbox_events` и ревизия для них находятся в `alembic/versions/`. На текущем стенде разработки миграции уже применены; для новой БД после запуска PostgreSQL просмотрите `upgrade()` и `downgrade()` ревизии и выполните:

```powershell
uv run --locked alembic upgrade head
```

Новые ревизии создавайте после следующих изменений моделей командой `uv run --locked alembic revision --autogenerate -m "update_payment_tables"`, проверяя сгенерированный код до применения. Команды Alembic используют переменные `DB_*` из окружения или `.env`; локальный адрес БД по умолчанию — `localhost:5432`. Миграции выполняются отдельным шагом, а не при старте API.

## See Also

- [REST API](api.md) — запросы, ответы и ошибки работающих маршрутов.
- [Требования](project.md) — оставшийся целевой процесс.
- [Переменные окружения](environment-variables.md) — значения конфигурации.
