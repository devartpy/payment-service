# payment-service

> Разработка микросервиса для асинхронной обработки платежей на FastAPI, PostgreSQL и RabbitMQ.

Репозиторий уже содержит запускаемый HTTP-каркас, настройки БД, логирование и границы платёжного модуля. [Требования к сервису](docs/project.md) и [диаграмма последовательности](docs/architecture/diagrams/payment-processing-sequence.puml) описывают целевое поведение. Создание платежей, consumer, outbox publisher и webhook пока не реализованы.

## Структура проекта

```text
src/
├── api/                 сборка FastAPI, общий маршрутизатор, Trace ID
├── common/              настройки, логирование, БД, Unit of Work
└── modules/payment/     каркас домена, сценариев, инфраструктуры и HTTP API
alembic/                 окружение и шаблон миграций
tests/common/            действующие тесты общей инфраструктуры
tests/payment/           каталоги для будущих тестов платежей
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
- Платёж и outbox-событие сохраняются в одной транзакции; publisher публикует событие в RabbitMQ и отмечает его после подтверждения брокера.
- Consumer обрабатывает сообщение, сохраняет результат и отправляет webhook. Для webhook предусмотрены три попытки с экспоненциальной задержкой; необработанные сообщения направляются в DLQ по отдельной политике.

Эти пункты — требования, не доступные сейчас функции API. Детали и критерии готовности указаны в [задании](docs/project.md).

## Документация

| Раздел | Описание |
| --- | --- |
| [Требования](docs/project.md) | Целевой процесс платежа и критерии результата. |
| [Запуск и разработка](docs/getting-started.md) | Окружение, Docker Compose, проверки и миграции. |
| [Архитектура](docs/architecture.md) | Структура модулей, зависимости и транзакции. |
| [Переменные окружения](docs/environment-variables.md) | Параметры API, PostgreSQL и логирования. |

Диаграмма: [последовательность обработки платежа](docs/architecture/diagrams/payment-processing-sequence.puml).

## Лицензия

[MIT](LICENSE).
