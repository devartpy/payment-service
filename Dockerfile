# syntax=docker/dockerfile:1

# Keep the default in sync with the template's Python 3.10 target.
ARG PYTHON_VERSION=3.10

FROM python:${PYTHON_VERSION}-slim AS builder
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy

COPY . ./
# In a new service, add its selected --extra flags to uv sync.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:${PYTHON_VERSION}-slim AS runtime
WORKDIR /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --home-dir /app app

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic/ ./alembic/

USER app
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
