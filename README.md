# payment-service

> Асинхронный платёжный сервис на FastAPI, PostgreSQL и RabbitMQ.

Сервис принимает платежи по HTTP и позволяет читать их состояние. При создании он сохраняет платёж со статусом `pending` и событие outbox в одной транзакции. Отдельный consumer обрабатывает опубликованное событие, сохраняет конечный статус и отправляет webhook.

Отдельный outbox publisher публикует событие в RabbitMQ, удаляет запись outbox после подтверждения брокера и фиксирует удаление. Публикация сама по себе не меняет статус; конечный результат сохраняет consumer после обработки. Полный процесс описан в [архитектуре](docs/architecture.md).

## Быстрый запуск

Для запуска нужны Docker Desktop с Compose, GNU Make и PowerShell. Из корня проекта:

```powershell
Copy-Item .env.example .env
```

Задайте в `.env` рабочие `DB_PASSWORD`, `API_KEY` и `RABBITMQ_PASSWORD`, затем выполните:

```powershell
make up
```

Команда поднимает PostgreSQL и RabbitMQ, собирает образы, применяет миграции и запускает API, consumer и publisher. Publisher ожидает готовности consumer. Для остановки без удаления данных используйте `make down`. Локальный запуск через `uv` описан в [руководстве для разработчика](docs/getting-started.md).

Для создания платежа в другом окне PowerShell (замените `merchant.example` на доступный webhook URL):

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' } | Select-Object -First 1) -replace '^API_KEY=', ''
$headers = @{ "X-API-Key" = $apiKey; "Idempotency-Key" = "example-001" }
$body = @{ amount = "12.50"; currency = "RUB"; description = "Заказ 1"; metadata = @{ order = "1" }; webhook_url = "https://merchant.example/hook" } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/payments -Headers $headers -ContentType application/json -Body $body
```

Ответ содержит `payment_id`, `status: "pending"` и `created_at` в UTC. Повтор с тем же `Idempotency-Key` возвращает `409`. Пример чтения и полный формат ошибок приведены в [справочнике API](docs/api.md).

## Что работает

- `POST /api/v1/payments` и `GET /api/v1/payments/{payment_id}` с проверкой `X-API-Key`.
- Обязательный `Idempotency-Key` для POST и отказ при повторном использовании ключа.
- Общий формат ошибок и атомарный `commit` платежа с outbox через SQLAlchemy Unit of Work.
- FastStream consumer: эмуляция шлюза со случайным исходом 90/10 и конечным статусом; отдельный subscriber доставляет webhook до трёх попыток через очереди задержки, а DLQ сохраняет окончательные отказы для разбора.
- Outbox relay: публикация с RabbitMQ confirm и проверкой маршрута, затем отдельный `commit` удаления для каждого события. После сбоя commit публикация может повториться.
- Интеграционные и HTTP-тесты на PostgreSQL с изоляцией во временных схемах; проверки consumer на одном RabbitMQ с отдельными очередями тестов.

## Документация

| Раздел | Описание |
| --- | --- |
| [Запуск и разработка](docs/getting-started.md) | Окружение, Compose, миграции и тесты. |
| [REST API](docs/api.md) | Запросы, ответы и ошибки платежей. |
| [Архитектура](docs/architecture.md) | Слои, транзакции и доставка событий. |
| [Переменные окружения](docs/environment-variables.md) | Настройки API, БД, RabbitMQ и логирования. |

## Диаграммы

- [Последовательность обработки платежа](docs/architecture/diagrams/payment-processing-sequence.puml)
- [Действия consumer и webhook](docs/architecture/diagrams/payment-consumer-activity.puml)
- [Контейнеры сервиса](docs/architecture/diagrams/payment-service-container.puml)

## Лицензия

[MIT](LICENSE).
