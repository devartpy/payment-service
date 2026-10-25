[К README](../README.md) · [REST API →](api.md)

# Запуск и разработка

Инструкции выполняются из корня репозитория. POST/GET платежей работают с PostgreSQL, consumer — с PostgreSQL и RabbitMQ. Outbox publisher ещё не подключён.

## Требования

| Инструмент | Для чего нужен |
| --- | --- |
| Python 3.10+ | Локальный запуск; Dockerfile и CI используют Python 3.10. |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Установка зависимостей по `uv.lock`. |
| Docker Desktop с Compose | Контейнеры API, consumer, PostgreSQL и RabbitMQ. |
| PowerShell | Команды ниже приведены для Windows. |

`uv.lock` уже входит в репозиторий. При изменении зависимостей обновите его командой `uv lock` и сохраняйте вместе с `pyproject.toml`.

## Локальный запуск API

1. Создайте конфигурацию, замените учебные `DB_PASSWORD=change-me`, `RABBITMQ_PASSWORD=change-me` и `API_KEY=replace-with-a-secret` в `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Создайте окружение и установите зависимости из lock-файла:

   ```powershell
   uv sync --python 3.10 --locked
   ```

3. Запустите PostgreSQL и RabbitMQ, примените миграции:

   ```powershell
   docker compose up -d db rabbitmq --wait
   uv run --locked alembic upgrade head
   ```

4. Запустите приложение:

   ```powershell
   uv run --locked uvicorn src.api.main:app --reload
   ```

   Во втором терминале запустите consumer:

   ```powershell
   uv run --locked faststream run src.consumer.app:app
   ```

   Подписчики consumer создают durable exchange `payments`, очередь `payments.new`, DLX `payments.dlx` и очередь `payments.dead_letter` при запуске. Первый ожидает событие `{"payment_id":"<UUID>"}`; второй логирует попадание сообщения в DLQ на уровне CRITICAL и подтверждает его. Сообщение после этого удаляется из DLQ. Поскольку outbox publisher ещё не реализован, POST создаёт платёж `new`, но сам не публикует сообщение и не переводит платёж в `pending`. Интеграционные тесты проверяют consumer с подготовленным `pending` платежом и прямой публикацией события.

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

Compose поднимает `api`, `consumer`, `db` и `rabbitmq`. Примените миграции отдельной командой с хоста: `uv run --locked alembic upgrade head`. Swagger UI доступен на `http://127.0.0.1:8000/docs`. Для остановки без удаления данных:

```powershell
docker compose down
```

В Compose есть отдельный процесс consumer с командой `faststream run src.consumer.app:app`; outbox publisher пока отсутствует. API создаёт фабрику асинхронных сессий при старте. Consumer использует один SQLAlchemy engine и одну фабрику сессий на весь процесс, а при остановке закрывает engine. Миграции не запускаются автоматически.

`DB_PORT` задаёт порт PostgreSQL на хосте; API и consumer внутри Compose подключаются к `db:5432`. Подробности приведены в [переменных окружения](environment-variables.md).

## Проверки

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

CI выполняет эти проверки для pull request и предварительно применяет миграции. Локальные интеграционные и HTTP-тесты используют запущенную PostgreSQL: каждый создаёт собственную временную схему, применяет к ней миграции и удаляет только эту схему. Тесты consumer используют один запущенный RabbitMQ и отдельные очереди/exchange для каждого теста, которые удаляются после него. Отдельная тестовая БД или новый контейнер на каждый тест не нужны. Для полного локального прогона запустите `docker compose up -d db rabbitmq --wait`. На Windows с GNU Make доступны `make lint`, `make test`, `make up`, `make down` и другие цели из `Makefile`.

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
