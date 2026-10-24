# payment-service

> Асинхронный платёжный сервис на FastAPI и PostgreSQL с атомарной записью платежа и outbox.

Сервис принимает платежи по HTTP и позволяет читать их состояние. При создании он сохраняет платёж со статусом `new` и событие outbox в одной транзакции. Публикация в RabbitMQ, обработка платежа и webhook пока не реализованы; полный целевой процесс описан в [требованиях](docs/project.md).

## Быстрый запуск

Нужны Python 3.10+, `uv`, PowerShell и доступная PostgreSQL. Из корня проекта:

```powershell
Copy-Item .env.example .env
```

Задайте в `.env` рабочие `DB_PASSWORD` и `API_KEY`, затем выполните:

```powershell
uv sync --python 3.10 --locked
docker compose up -d db --wait
uv run --locked alembic upgrade head
uv run --locked uvicorn src.api.main:app --reload
```

Для создания платежа в другом окне PowerShell:

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' } | Select-Object -First 1) -replace '^API_KEY=', ''
$headers = @{ "X-API-Key" = $apiKey; "Idempotency-Key" = "example-001" }
$body = @{ amount = "12.50"; currency = "RUB"; description = "Заказ 1"; metadata = @{ order = "1" }; webhook_url = "https://merchant.example/hook" } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/payments -Headers $headers -ContentType application/json -Body $body
```

Ответ содержит `payment_id`, `status: "new"` и `created_at` в UTC. Повтор с тем же `Idempotency-Key` возвращает `409`. Пример чтения и полный формат ошибок приведены в [справочнике API](docs/api.md).

## Что работает

- `POST /api/v1/payments` и `GET /api/v1/payments/{payment_id}` с проверкой `X-API-Key`.
- Обязательный `Idempotency-Key` для POST и отказ при повторном использовании ключа.
- Общий формат ошибок и атомарный `commit` платежа с outbox через SQLAlchemy Unit of Work.
- Интеграционные и HTTP-тесты на PostgreSQL с изоляцией во временных схемах.

## Документация

| Раздел | Описание |
| --- | --- |
| [Запуск и разработка](docs/getting-started.md) | Окружение, Compose, миграции и тесты. |
| [REST API](docs/api.md) | Запросы, ответы и ошибки платежей. |
| [Архитектура](docs/architecture.md) | Слои, транзакции и целевые интеграции. |
| [Переменные окружения](docs/environment-variables.md) | Настройки API, БД и логирования. |
| [Требования](docs/project.md) | Полный целевой сценарий и критерии. |

Диаграммы: [последовательность](docs/architecture/diagrams/payment-processing-sequence.puml), [consumer](docs/architecture/diagrams/payment-consumer-activity.puml), [контейнеры](docs/architecture/diagrams/payment-service-container.puml).

## Лицензия

[MIT](LICENSE).
