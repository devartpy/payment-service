# payment-service

> Модульный шаблон FastAPI с DDD, PostgreSQL, Alembic и структурированными логами.

HTTP-приложение запускается сразу; бизнес-маршруты, модели и миграции добавляются в новом сервисе.

## Создание нового сервиса

Все команды ниже выполняются в PowerShell из корня нового репозитория. Понадобятся [uv](https://docs.astral.sh/uv/getting-started/installation/), VS Code и Docker Desktop. В примерах используется Python 3.10 и имя модуля `payments`: замените их на выбранные для сервиса.

1. **Создайте репозиторий.** На GitHub нажмите **Use this template**, создайте репозиторий сервиса, клонируйте его на Windows и откройте папку в VS Code.

2. **Переименуйте бизнес-модуль и каталог его тестов.** Имя должно отражать предметную область:

   ```powershell
   Rename-Item src\modules\module1 payments
   Rename-Item tests\module1 payments
   ```

   Замените упоминания `module1` в [описании архитектуры](docs/architecture.md) на имя своего модуля. Имя Python-пакета `src` менять не нужно.

3. **Задайте имя проекта и версию Python.** В `pyproject.toml` измените `[project].name` и `description`. Укажите поддерживаемый диапазон `requires-python` (например, `>=3.10,<3.11`, если сервис использует только Python 3.10). Согласуйте с ним `ARG PYTHON_VERSION` в `Dockerfile`, `python-version` в `.github/workflows/ci.yml` и `target-version` Ruff в `pyproject.toml` (`py310` для Python 3.10).

4. **Выберите дополнительные зависимости.** Redis, RabbitMQ и Kafka объявлены как extras в `pyproject.toml`; если они не нужны, пропустите этот шаг. Для нужного extra добавьте, например, `--extra redis` к команде `uv sync` в `Dockerfile`. Те же флаги используйте в локальных командах `uv sync` и `uv run`; можно указать несколько `--extra`. Если тестам нужны эти зависимости, добавьте флаги и к `uv sync` в `.github/workflows/ci.yml`.

5. **Создайте локальное окружение.** Скопируйте пример и задайте в `.env` как минимум собственные `DB_USER`, `DB_PASSWORD` и `FA_TITLE`. Файл `.env` исключён из Git.

   ```powershell
   Copy-Item .env.example .env
   ```

   Значения остальных переменных описаны в [Environment Variables](docs/environment-variables.md).

6. **Зафиксируйте зависимости и создайте `.venv`.** В шаблоне нет `uv.lock`: новый сервис получает актуальные совместимые версии при первом разрешении зависимостей. В примере оставлен Python 3.10; при выборе другой версии замените её в команде.

   ```powershell
   uv lock --upgrade
   uv sync --python 3.10 --locked
   ```

   При выборе extras добавьте соответствующие `--extra` к `uv sync`. VS Code использует созданный `.venv\Scripts\python.exe` согласно `.vscode/settings.json`.

7. **Проверьте код и локальный запуск.** При использовании extras добавляйте те же флаги к командам `uv run`.

   ```powershell
   uv run --locked ruff check .
   uv run --locked ruff format --check .
   uv run --locked pytest
   uv build
   uv run --locked uvicorn src.api.main:app --reload
   ```

   Откройте `http://127.0.0.1:8000/docs`: Swagger UI доступен и без бизнес-маршрутов. После проверки остановите Uvicorn сочетанием `Ctrl+C`.

8. **Проверьте Docker-сборку и запуск.** Для сборки нужен созданный на шаге 6 `uv.lock`; образ устанавливает зависимости строго по нему через `uv sync --locked`. Compose дождётся готовности PostgreSQL перед запуском API.

   ```powershell
   docker compose build api
   docker compose up -d --wait
   docker compose ps
   ```

   Проверьте `http://127.0.0.1:8000/docs`, затем остановите окружение:

   ```powershell
   docker compose down
   ```

   Если локальный порт PostgreSQL `5432` занят, задайте `DB_HOST_PORT` в `.env`. Для локального запуска Alembic на другом порту отдельно передайте такое же значение в `DB_PORT`.

9. **Закоммитьте настройку сервиса вместе с `uv.lock`.** Проверьте список файлов перед коммитом: `.env` в него попадать не должен. CI разрешает отсутствие lock-файла только в исходном репозитории `devartpy/fastapi-ms-template`; в созданном сервисе PR без `uv.lock` завершится ошибкой. После изменения зависимостей обновляйте lock-файл командой `uv lock` и коммитьте его вместе с `pyproject.toml`.

   ```powershell
   git status --short
   git add -A
   git diff --cached --stat
   git commit -m "chore: initialize service from template"
   ```

## Дальнейшая разработка

Подключайте маршруты модулей в `src/api/main_router.py`. `src/api/main.py` настраивает логирование API и `TraceIdMiddleware`, а `src/api/app.py` собирает FastAPI. Для отдельных процессов (`scheduler`, `consumer`) вызывайте `setup_logger(service_name="...")` в их точках запуска.

Ruff форматирует Python-файлы при сохранении в VS Code. Если на Windows установлен GNU Make, доступны `make up`, `make down`, `make restart`, `make lint` и `make test`.

После добавления ORM-моделей создайте миграцию, проверьте ревизию и примените её. С GNU Make используйте `make migration m=init_tables` и `make upgrade`; без него выполните команды из корня проекта:

```powershell
docker compose up -d --wait db
uv run --locked alembic revision --autogenerate -m "init_tables"
uv run --locked alembic upgrade head
```

Alembic автоматически импортирует `src/modules/*/infrastructure/db/models.py`. Локальные команды подключаются к PostgreSQL на `127.0.0.1:5432` по умолчанию. Если для Compose задан другой `DB_HOST_PORT`, в текущем PowerShell перед запуском Alembic установите `$env:DB_PORT` в то же значение; контейнеру API нужен внутренний порт БД `5432`.

## Документация

| Раздел | Описание |
| --- | --- |
| [Архитектура](docs/architecture.md) | Слои, Unit of Work, миграции и контракт логов. |
| [Environment Variables](docs/environment-variables.md) | Переменные окружения, значения по умолчанию и формат. |

## Лицензия

[MIT](LICENSE).
