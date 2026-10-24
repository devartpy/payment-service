# payment-service

> Разработка микросервиса для асинхронной обработки платежей на FastAPI, PostgreSQL и RabbitMQ.

Репозиторий содержит запускаемый HTTP-каркас, настройки БД, логирование, доменные и ORM-модели платежа и черновую миграцию. [Требования к сервису](docs/project.md) и [диаграмма последовательности](docs/architecture/diagrams/payment-processing-sequence.puml) описывают целевое поведение. Платёжные маршруты, publisher, consumer и webhook пока не реализованы.

## Структура проекта

```text
src/
├── api/                 сборка FastAPI, общий маршрутизатор, Trace ID
├── common/              настройки, логирование, БД, Unit of Work
└── modules/payments/    доменные и ORM-модели; каркас сценариев и HTTP API
alembic/                 окружение и черновая миграция таблиц платежей
tests/common/            действующие тесты общей инфраструктуры
tests/payments/          каталоги для будущих тестов платежей
docs/                    требования, руководство и архитектура
```

Точка входа — `src.api.main:app`. Маршрутизатор `src/api/main_router.py` пока не содержит платёжных эндпоинтов. Подробное назначение слоёв — в [архитектуре](docs/architecture.md).

## Быстрый запуск

Нужны Python 3.10+, [uv](https://docs.astral.sh/uv/getting-started/installation/) и PowerShell. Из корня репозитория:

```powershell
Copy-Item .env.example .env
uv sync --python 3.10 --locked
uv run --locked uvicorn src.api.main:app --reload
```

Замените `DB_PASSWORD=change-me` в `.env` до подключения БД. Откройте `http://127.0.0.1:8000/docs`: Swagger UI работает уже сейчас, но маршрутов платежей в нём пока нет. Для контейнерного запуска и проверок см. [руководство по запуску](docs/getting-started.md).

## Проверка работающего каркаса

При запущенном API выполните:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/openapi.json | Select-Object -ExpandProperty StatusCode
```

Ожидаемый ответ — `200`. Это проверяет HTTP-приложение, а не целевой сценарий платежа.

## Планируемый платёжный процесс

- `POST /api/v1/payments` принимает обязательные `X-API-Key` и `Idempotency-Key`, создаёт платёж и возвращает `202 Accepted`; `GET /api/v1/payments/{payment_id}` выдаёт его состояние.
- API сохраняет `Payment(NEW)` и OutboxEvent в одной транзакции. Publisher публикует событие в `payments.new`; после подтверждения RabbitMQ он одной транзакцией переводит платёж `NEW → PENDING` и удаляет запись outbox.
- Один consumer обрабатывает `PENDING` через идемпотентный шлюз, сохраняет конечный статус `SUCCEEDED` или `FAILED` и отправляет webhook. Для webhook допускаются три попытки при сбое сети, таймауте или `5xx`; при `4xx` либо исчерпании попыток исходное сообщение попадает в `payments.dlq`.

Эти пункты — требования, не доступные сейчас функции API. Детали и критерии готовности указаны в [задании](docs/project.md).

## Документация

| Раздел | Описание |
| --- | --- |
| [Требования](docs/project.md) | Целевой процесс платежа и критерии результата. |
| [Запуск и разработка](docs/getting-started.md) | Окружение, Docker Compose, проверки и миграции. |
| [Архитектура](docs/architecture.md) | Структура модулей, зависимости и транзакции. |
| [Переменные окружения](docs/environment-variables.md) | Параметры API, PostgreSQL и логирования. |

Диаграммы: [последовательность](docs/architecture/diagrams/payment-processing-sequence.puml), [обработка consumer](docs/architecture/diagrams/payment-consumer-activity.puml), [контейнеры](docs/architecture/diagrams/payment-service-container.puml).

## Лицензия

[MIT](LICENSE).
