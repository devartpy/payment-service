[← Архитектура](architecture.md) · [К README](../README.md)

# Переменные окружения

Настройки определены в `src/common/configs/`. Скопируйте `.env.example` в `.env` из корня проекта и замените значения для своего сервиса. `.env` предназначен для локальной разработки; при запуске в контейнере передавайте настройки через окружение процесса. Переменная окружения имеет приоритет над одноимённым значением из `.env`.

```powershell
Copy-Item .env.example .env
```

`DB_USER` и `DB_PASSWORD` обязательны при создании `DatabaseConfig`; `API_KEY` обязателен при создании `FastAPIConfig`. API, consumer и publisher создают собственные движки и фабрики сессий. Команды Alembic тоже читают `DB_*`. Замените `DB_PASSWORD=change-me`, `RABBITMQ_PASSWORD=change-me` и `API_KEY=replace-with-a-secret` в примере. Не храните рабочие секреты в Git.

## Приложение и логирование

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `APP_LOG_LEVEL` | `INFO` | Уровень Python logging: `DEBUG`, `INFO`, `WARNING`, `ERROR` или `CRITICAL`. |
| `APP_JSON_LOGS` | `true` | `true` — JSON по строке на событие; `false` — читаемый формат для локальной разработки. |

Имя для поля `service` передаётся при настройке логирования, например `setup_logger(service_name="api")`, `setup_logger(service_name="consumer")` или `setup_logger(service_name="publisher")`. Это имя относится к процессу, а не к переменной окружения. Publisher пишет INFO после подтверждения RabbitMQ и фиксации удаления, WARNING/ERROR при сбоях, DEBUG при опросе outbox; payload, ключи и секреты в лог не передаются.

## PostgreSQL

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DB_HOST` | `localhost` | Хост PostgreSQL; внутри контейнера обычно имя сервиса базы данных. |
| `DB_PORT` | `5432` | Порт PostgreSQL, целое число. |
| `DB_USER` | нет, обязательна | Пользователь базы данных. |
| `DB_PASSWORD` | нет, обязательна | Пароль пользователя базы данных. |
| `DB_NAME` | `db` | Имя базы данных. |

`DatabaseConfig.async_url` собирает SQLAlchemy URL из этих полей. Специальные символы в пароле не нужно экранировать вручную.

## RabbitMQ

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `RABBITMQ_HOST` | `localhost` | Хост брокера; для процесса внутри Compose используется имя сервиса `rabbitmq`. |
| `RABBITMQ_PORT` | `5672` | AMQP-порт брокера на хосте. |
| `RABBITMQ_USER` | `guest` | Пользователь AMQP. |
| `RABBITMQ_PASSWORD` | `guest` | Пароль AMQP. Задайте собственное значение в `.env`. |
| `RABBITMQ_VHOST` | `/` | Виртуальный хост; значение кодируется при построении AMQP URL. |

`RabbitMQConfig` собирает URL и кодирует логин, пароль и vhost. Consumer создаёт exchange и очереди при запуске; publisher использует готовую топологию. Compose открывает AMQP-порт на `127.0.0.1` и интерфейс управления на `127.0.0.1:15672`. Для уже созданного тома RabbitMQ смена логина/пароля через переменные Compose не перенастраивает существующего пользователя; настройте его в брокере либо используйте новый том в новом стенде.

Имена exchange и очередей заданы константами в `src/common/configs/rabbitmq_config.py` и через `.env` не настраиваются. Routing key совпадают с именами соответствующих очередей.

В `docker-compose.yaml` переменная `DB_PORT` задаёт опубликованный порт PostgreSQL на хосте. Процессы API, consumer и publisher внутри сети Compose используют `db:5432`. Для локальных команд Alembic и тестов укажите в `.env` порт, опубликованный на хосте. Подробности запуска — в [руководстве](getting-started.md).

## FastAPI

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `FA_TITLE` | `FastAPI Service` | Заголовок приложения FastAPI; не может быть пустым. |
| `FA_CORS_ORIGINS` | `[]` | Разрешённые источники CORS в виде JSON-массива строк. |
| `FA_ENABLE_DOCS` | `true` | Флаг для включения документации при сборке приложения. |
| `FA_OPENAPI_URL` | `/openapi.json` | Путь к схеме OpenAPI. |
| `FA_DOCS_URL` | `/docs` | Путь к Swagger UI. |
| `FA_REDOC_URL` | `/redoc` | Путь к ReDoc. |
| `API_KEY` | нет, обязателен | Статический ключ для проверки заголовка `X-API-Key` на платёжных маршрутах. |

Пример значения списка: `FA_CORS_ORIGINS=["http://localhost:3000","https://example.com"]`. Если список пуст, CORS middleware не подключается. `FA_ENABLE_DOCS=false` отключает схему OpenAPI, Swagger UI и ReDoc при создании приложения.

## Правила чтения

Все классы наследуют `CommonConfig`: он читает `.env` в UTF-8 из текущего рабочего каталога и игнорирует лишние ключи. Функции `get_db_config()`, `get_fastapi_config()`, `get_logger_config()` и `get_rabbitmq_config()` кешируют объекты после первого вызова. После изменения окружения в уже работающем процессе нужен перезапуск либо очистка кеша соответствующей функции в тесте.

## See Also

- [Запуск и разработка](getting-started.md) — локальное окружение и Compose.
- [REST API](api.md) — как передать ключ при обращении к платежам.
- [Архитектура](architecture.md) — использование настроек в процессах сервиса.
