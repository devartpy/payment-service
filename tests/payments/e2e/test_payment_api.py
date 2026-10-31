"""Сквозные HTTP-проверки в изолированной схеме текущего PostgreSQL."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.api.app import create_app
from src.api.dependencies import get_payment_uow_factory
from src.common.configs import get_fastapi_config
from src.modules.payments.domain.value_objects import PaymentStatus
from src.modules.payments.infrastructure.db import models as orm
from src.modules.payments.infrastructure.repositories import SQLAlchemyOutboxRepository

HEADERS = {"X-API-Key": "test-secret", "Idempotency-Key": "test-payment"}
BODY = {
    "amount": "12.50",
    "currency": "RUB",
    "description": "Test payment",
    "metadata": {"order": "first"},
    "webhook_url": "https://merchant.example/hook",
}


@pytest.fixture
def payment_app(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> Iterator[FastAPI]:
    monkeypatch.setenv("API_KEY", "test-secret")
    get_fastapi_config.cache_clear()
    app = create_app()
    app.state.session_factory = session_factory
    yield app
    get_fastapi_config.cache_clear()


async def counts(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with session_factory() as session:
        payments = await session.scalar(select(func.count()).select_from(orm.Payment))
        events = await session.scalar(select(func.count()).select_from(orm.OutboxEvent))
    return int(payments or 0), int(events or 0)


@pytest.mark.asyncio
async def test_create_get_and_duplicate_key_keep_one_outbox(
    payment_app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=payment_app), base_url="http://test") as client:
        created = await client.post("/api/v1/payments", headers=HEADERS, json=BODY)
        duplicate = await client.post("/api/v1/payments", headers=HEADERS, json=BODY)
        fetched = await client.get(
            f"/api/v1/payments/{created.json()['payment_id']}", headers={"X-API-Key": "test-secret"}
        )

    assert created.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json() == created.json()
    assert created.json()["status"] == "pending"
    assert created.json()["created_at"].endswith("Z")
    assert fetched.status_code == 200
    assert fetched.json()["amount"] == "12.50"
    assert fetched.json()["status"] == "pending"
    assert fetched.json()["metadata"] == BODY["metadata"]
    assert fetched.json()["processed_at"] is None
    assert await counts(session_factory) == (1, 1)

    payment_id = UUID(created.json()["payment_id"])
    async with session_factory() as session:
        stored_payment = await session.get(orm.Payment, payment_id)
        stored_event = (await session.scalars(select(orm.OutboxEvent))).one()
    assert stored_payment is not None
    assert stored_payment.status is PaymentStatus.PENDING
    assert stored_payment.created_at.utcoffset().total_seconds() == 0
    assert stored_event.payload == {"payment_id": str(payment_id)}
    assert stored_event.created_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_replay_with_different_body_returns_original_payment_and_keeps_one_outbox(
    payment_app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=payment_app), base_url="http://test") as client:
        first = await client.post("/api/v1/payments", headers=HEADERS, json=BODY)
        replay = await client.post(
            "/api/v1/payments", headers=HEADERS, json={**BODY, "description": "Different payment"}
        )

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert await counts(session_factory) == (1, 1)


@pytest.mark.asyncio
async def test_auth_headers_not_found_and_validation_share_error_shape(payment_app: FastAPI) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=payment_app), base_url="http://test") as client:
        no_auth = await client.post("/api/v1/payments", headers={"Idempotency-Key": "one"}, json=BODY)
        bad_auth = await client.get(f"/api/v1/payments/{uuid4()}", headers={"X-API-Key": "wrong"})
        no_idempotency = await client.post("/api/v1/payments", headers={"X-API-Key": "test-secret"}, json=BODY)
        missing = await client.get(f"/api/v1/payments/{uuid4()}", headers={"X-API-Key": "test-secret"})
        invalid = await client.post("/api/v1/payments", headers=HEADERS, json={**BODY, "currency": "GBP"})
        unknown = await client.get("/api/v1/unknown", headers={"X-API-Key": "test-secret"})

    for response, status, code in (
        (no_auth, 401, "UNAUTHORIZED"),
        (bad_auth, 401, "UNAUTHORIZED"),
        (no_idempotency, 400, "INVALID_IDEMPOTENCY_KEY"),
        (missing, 404, "PAYMENT_NOT_FOUND"),
        (invalid, 422, "VALIDATION_ERROR"),
        (unknown, 404, "HTTP_ERROR"),
    ):
        assert response.status_code == status
        assert set(response.json()["error"]) == {"code", "message", "meta"}
        assert response.json()["error"]["code"] == code
        assert "test-secret" not in response.text


@pytest.mark.asyncio
async def test_domain_error_codes_and_private_url_are_not_exposed(payment_app: FastAPI) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=payment_app), base_url="http://test") as client:
        amount = await client.post("/api/v1/payments", headers=HEADERS, json={**BODY, "amount": "0"})
        url = await client.post(
            "/api/v1/payments", headers=HEADERS, json={**BODY, "webhook_url": "private-webhook-value"}
        )

    assert amount.status_code == url.status_code == 400
    assert amount.json()["error"]["code"] == "PAYMENT_AMOUNT_TOO_LOW"
    assert url.json()["error"]["code"] == "INVALID_WEBHOOK_URL"
    assert "private-webhook-value" not in url.text


@pytest.mark.asyncio
async def test_unexpected_failure_is_safe(payment_app: FastAPI) -> None:
    def failing_factory() -> None:
        raise RuntimeError("private database detail")

    payment_app.dependency_overrides[get_payment_uow_factory] = failing_factory
    transport = httpx.ASGITransport(app=payment_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/payments", headers=HEADERS, json=BODY)

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "Внутренняя ошибка сервера",
        "meta": {},
    }
    assert "private database detail" not in response.text


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_payment(
    payment_app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_outbox(_repository: SQLAlchemyOutboxRepository, _event: object) -> None:
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(SQLAlchemyOutboxRepository, "add", fail_outbox)
    transport = httpx.ASGITransport(app=payment_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/payments", headers=HEADERS, json=BODY)

    assert response.status_code == 500
    assert await counts(session_factory) == (0, 0)
