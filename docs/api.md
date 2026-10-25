[← Запуск и разработка](getting-started.md) · [К README](../README.md) · [Архитектура →](architecture.md)

# REST API платежей

Базовый адрес локального сервиса — `http://127.0.0.1:8000`. Операции описаны в `/docs`, если `FA_ENABLE_DOCS=true`. Все маршруты платежей требуют заголовок `X-API-Key` со значением `API_KEY` из окружения сервиса.

## Создать платёж

`POST /api/v1/payments` требует дополнительный заголовок `Idempotency-Key`: непустую строку длиной не более 255 символов. При успешном запросе возвращается `202 Accepted`.

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' } | Select-Object -First 1) -replace '^API_KEY=', ''
$headers = @{ "X-API-Key" = $apiKey; "Idempotency-Key" = "order-001" }
$body = @{ amount = "12.50"; currency = "RUB"; description = "Заказ 1"; metadata = @{ order = "1" }; webhook_url = "https://merchant.example/hook" } | ConvertTo-Json -Depth 5
$created = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/payments -Headers $headers -ContentType application/json -Body $body
$created
```

| Поле JSON | Требование |
| --- | --- |
| `amount` | Положительное десятичное число, до 15 цифр и 2 знаков после запятой; в примере передаётся строкой. |
| `currency` | `RUB`, `USD` или `EUR`. |
| `description` | Строка до 255 символов. |
| `metadata` | Произвольный JSON-объект; по умолчанию `{}`. |
| `webhook_url` | Строка до 512 символов с URL схемы `http` или `https`. |

Пример ответа:

```json
{
  "payment_id": "a222b9ac-8519-4d4b-a17e-6e51c555a1e8",
  "status": "pending",
  "created_at": "2026-10-25T00:00:00Z"
}
```

Платёж со статусом `pending` и событие outbox создаются одним `commit` в PostgreSQL. Ответ `202` означает сохранение для последующей обработки, а не подтверждение публикации в RabbitMQ. Отдельный publisher доставляет событие, после чего consumer сохраняет конечный статус. Пока оба процесса не работают, платёж остаётся `pending`. Последовательный повтор с уже использованным `Idempotency-Key` получает `409` независимо от тела запроса. Специальная обработка гонки двух одновременных запросов с одинаковым ключом пока не реализована.

## Получить платёж

`GET /api/v1/payments/{payment_id}` принимает UUID платежа и заголовок `X-API-Key`. При успехе возвращает `200 OK`:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/payments/$($created.payment_id)" -Headers @{ "X-API-Key" = $apiKey }
```

Команда использует `payment_id` из предыдущего ответа. Пример тела ответа:

```json
{
  "payment_id": "a222b9ac-8519-4d4b-a17e-6e51c555a1e8",
  "amount": "12.50",
  "currency": "RUB",
  "description": "Заказ 1",
  "metadata": {"order": "1"},
  "status": "pending",
  "webhook_url": "https://merchant.example/hook",
  "created_at": "2026-10-25T00:00:00Z",
  "processed_at": null
}
```

Все значения даты и времени передаются в UTC. Неизвестный UUID возвращает `404`.

## Ошибки

Все ошибки API имеют вид:

```json
{"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "Ключ идемпотентности уже использован", "meta": {}}}
```

| HTTP | `error.code` | Причина |
| --- | --- | --- |
| 400 | `INVALID_IDEMPOTENCY_KEY` | Заголовок отсутствует, пустой или длиннее 255 символов. |
| 400 | `PAYMENT_AMOUNT_TOO_LOW`, `INVALID_WEBHOOK_URL` | Нарушено правило домена. |
| 401 | `UNAUTHORIZED` | `X-API-Key` отсутствует или не совпадает с `API_KEY`. |
| 404 | `PAYMENT_NOT_FOUND` | Платёж не найден. |
| 409 | `IDEMPOTENCY_CONFLICT` | Ключ уже использован. |
| 422 | `VALIDATION_ERROR` | Некорректное тело запроса или параметр пути; `meta.fields` содержит имена полей. |
| 500 | `INTERNAL_ERROR` | Непредвиденная ошибка сервера; детали не раскрываются в ответе. |

Неизвестный путь возвращает `HTTP_ERROR` и соответствующий HTTP-статус. Сообщения об ошибках не содержат API-ключ и исходный webhook URL.

## See Also

- [Запуск и разработка](getting-started.md) — подготовка БД и запуск API.
- [Архитектура](architecture.md) — границы транзакции и слои кода.
- [Требования](project.md) — полный целевой процесс обработки.
