[К README](../README.md) · [REST API →](api.md)

# Запуск и разработка

Инструкции выполняются из корня репозитория. Основной запуск — через `make up`: API, consumer и publisher работают как отдельные процессы с общей PostgreSQL и RabbitMQ.

## Требования

| Инструмент | Для чего нужен |
| --- | --- |
| [GNU Make](https://www.gnu.org/software/make/) | Основные команды запуска и управления стендом. |
| Docker Desktop с Compose | Контейнеры API, consumer, publisher, PostgreSQL и RabbitMQ. |
| PowerShell | Команды ниже приведены для Windows. |
| Python 3.10+ и [uv](https://docs.astral.sh/uv/getting-started/installation/) | Локальная разработка, тесты и создание миграций; для `make up` не нужны. |

`uv.lock` уже входит в репозиторий. При изменении зависимостей обновите его командой `uv lock` и сохраняйте вместе с `pyproject.toml`.

## Запуск через Make

1. Скопируйте пример настроек и замените учебные `DB_PASSWORD=change-me`, `RABBITMQ_PASSWORD=change-me` и `API_KEY=replace-with-a-secret`:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Соберите и запустите стенд:

   ```powershell
   make up
   ```

   `make up` ждёт готовности PostgreSQL и RabbitMQ, собирает образы, применяет миграции в разовом контейнере и затем запускает API, consumer и publisher. Publisher стартует после успешного healthcheck consumer. Миграции выполняются до старта приложения.

3. Откройте `http://127.0.0.1:8000/docs` или проверьте OpenAPI:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/openapi.json | Select-Object -ExpandProperty StatusCode
   ```

   Ожидаемый код — `200`. Пример создания и чтения платежа находится в [REST API](api.md). Для остановки без удаления данных выполните `make down`.

| Команда | Действие |
| --- | --- |
| `make up` | Собрать образы, применить миграции и запустить весь стенд. |
| `make down` | Остановить контейнеры, сохранить тома. |
| `make restart` | Перезапустить уже созданные контейнеры. |
| `make upgrade` | Собрать образ API и применить миграции без запуска всех ролей. |
| `make lint`, `make test`, `make ci` | Проверки для разработки; требуют локальный `uv`. |

## Локальный запуск через uv

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

   После запуска consumer в третьем терминале запустите publisher:

   ```powershell
   uv run --locked python -m src.publisher.main
   ```

   Подписчики consumer создают durable exchange `payments`, очередь `payments.new`, DLX `payments.dlx` и очередь `payments.dead_letter`. Publisher не объявляет топологию: он читает outbox и публикует событие `{"payment_id":"<UUID>"}` в готовую очередь. Второй подписчик consumer логирует попадание сообщения в DLQ на уровне CRITICAL и подтверждает его.

5. Откройте `http://127.0.0.1:8000/docs` или проверьте доступность схемы:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/openapi.json | Select-Object -ExpandProperty StatusCode
   ```

   Ожидаемый код — `200`. В OpenAPI есть POST и GET платежей. Пример создания и чтения — в [REST API](api.md). Остановите Uvicorn клавишами `Ctrl+C`.

В Compose consumer использует `faststream run src.consumer.app:app`, publisher — `python -m src.publisher.main`. Каждый процесс создаёт свой SQLAlchemy engine и закрывает его при остановке. Publisher разворачивается в одном экземпляре.

`DB_PORT` задаёт порт PostgreSQL на хосте; API, consumer и publisher внутри Compose подключаются к `db:5432`. Подробности приведены в [переменных окружения](environment-variables.md).

## Проверки

```powershell
make lint
make test
uv run --locked pytest --cov=src --cov-report=term-missing
make ci
```

`make lint` и `make test` используют локальный `uv`. `make ci` запускает эти проверки и собирает образ API. Команда с `--cov` показывает общий процент покрытия в строке `TOTAL` и непроверенные строки в столбце `Missing`. В GitHub CI отдельно выполняются Ruff, pytest и сборка Python-пакета для pull request; отчёт покрытия пока создаётся только локальной командой.

Локальные интеграционные и HTTP-тесты используют запущенную PostgreSQL: каждый создаёт собственную временную схему, применяет к ней миграции и удаляет только эту схему. Тесты consumer и publisher используют один запущенный RabbitMQ и отдельные очереди/exchange для каждого теста, которые удаляются после него. Отдельная тестовая БД или новый контейнер на каждый тест не нужны. Перед полным локальным прогоном выполните `make infra-up`.

## Миграции

`alembic/env.py` импортирует ORM-модели из `src/modules/*/infrastructure/db/models.py`. Модели `payments` и `outbox_events` и ревизия для них находятся в `alembic/versions/`. `make up` применяет миграции перед запуском приложения. Чтобы применить их отдельно, выполните:

```powershell
make upgrade
```

Для новой ревизии используйте `make migration m=update_payment_tables` и проверьте сгенерированные `upgrade()` и `downgrade()` до применения. Эта команда требует локальный `uv`; прямой вариант — `uv run --locked alembic revision --autogenerate -m "update_payment_tables"`. Alembic читает `DB_*` из окружения или `.env`; локальный адрес БД по умолчанию — `localhost:5432`.

## See Also

- [REST API](api.md) — запросы, ответы и ошибки работающих маршрутов.
- [Архитектура](architecture.md) — жизненный цикл платежа и доставка событий.
- [Переменные окружения](environment-variables.md) — значения конфигурации.
