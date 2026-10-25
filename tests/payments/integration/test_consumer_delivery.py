"""Consumer на текущих PostgreSQL и RabbitMQ с изолированными ресурсами."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from faststream import AckPolicy
from faststream.rabbit import Channel, ExchangeType, RabbitBroker, RabbitExchange, RabbitMessage, RabbitQueue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.configs import get_rabbitmq_config
from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import Currency, PaymentStatus
from src.modules.payments.infrastructure import consumer as consumer_module
from src.modules.payments.infrastructure.consumer import handle_failed_payments_dlq, handle_payment
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork
from src.modules.payments.infrastructure.webhook import HTTPWebhookNotifier


class CountingGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, _payment: Payment) -> PaymentStatus:
        self.calls += 1
        return PaymentStatus.SUCCEEDED


class CountingNotifier:
    def __init__(self) -> None:
        self.calls = 0

    async def notify(self, _payment: Payment) -> bool:
        self.calls += 1
        return True


class FakeClient:
    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


@dataclass
class RabbitCase:
    broker: RabbitBroker
    exchange: RabbitExchange
    source: RabbitQueue
    dlq: RabbitQueue
    dlx: RabbitExchange
    dead_letters: asyncio.Queue[tuple[bytes, dict[str, Any]]]


@pytest.fixture
async def rabbit_case() -> AsyncIterator[RabbitCase]:
    suffix = uuid4().hex
    exchange = RabbitExchange(f"test.payments.{suffix}", type=ExchangeType.DIRECT, durable=True)
    dlx = RabbitExchange(f"test.payments.dlx.{suffix}", type=ExchangeType.DIRECT, durable=True)
    routing_key = f"test.payments.new.{suffix}"
    dlq_routing_key = f"test.payments.dlq.{suffix}"
    source = RabbitQueue(
        f"test.payments.new.{suffix}",
        durable=True,
        routing_key=routing_key,
        arguments={
            "x-dead-letter-exchange": dlx.name,
            "x-dead-letter-routing-key": dlq_routing_key,
            "x-single-active-consumer": True,
        },
    )
    dlq = RabbitQueue(f"test.payments.dlq.{suffix}", durable=True, routing_key=dlq_routing_key)
    broker = RabbitBroker(get_rabbitmq_config().url, default_channel=Channel(prefetch_count=1))
    dead_letters: asyncio.Queue[tuple[bytes, dict[str, Any]]] = asyncio.Queue()

    @broker.subscriber(dlq, dlx, ack_policy=AckPolicy.ACK)
    async def handle_dead_letter(payload: dict[str, object], message: RabbitMessage) -> None:
        body = message.raw_message.body
        headers = message.headers
        await handle_failed_payments_dlq(payload)
        dead_letters.put_nowait((body, headers))

    try:
        yield RabbitCase(broker, exchange, source, dlq, dlx, dead_letters)
    finally:
        await broker.stop()
        await broker.connect()
        await (await broker.declare_queue(source)).delete(if_unused=False, if_empty=False)
        await (await broker.declare_queue(dlq)).delete(if_unused=False, if_empty=False)
        await (await broker.declare_exchange(exchange)).delete(if_unused=False)
        await (await broker.declare_exchange(dlx)).delete(if_unused=False)
        await broker.stop()


def make_payment() -> Payment:
    return Payment(
        amount=Decimal("15.00"),
        currency=Currency.RUB,
        description="Rabbit test",
        webhook_url="https://merchant.example/hook",
        idempotency_key=uuid4().hex,
    )


async def wait_for(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.05)

    await asyncio.wait_for(poll(), timeout=timeout)


def register_test_payment_subscriber(
    rabbit_case: RabbitCase,
) -> None:
    @rabbit_case.broker.subscriber(rabbit_case.source, rabbit_case.exchange, ack_policy=AckPolicy.REJECT_ON_ERROR)
    async def handle_test_payment(payload: dict[str, object]) -> None:
        await handle_payment(payload)


def configure_test_handler(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: CountingGateway,
    notifier: CountingNotifier | HTTPWebhookNotifier,
) -> None:
    monkeypatch.setattr(consumer_module, "session_factory", session_factory)
    monkeypatch.setattr(consumer_module, "SimulatedPaymentGateway", lambda: gateway)
    monkeypatch.setattr(consumer_module, "HTTPWebhookNotifier", lambda _client: notifier)
    monkeypatch.setattr(consumer_module, "httpx", SimpleNamespace(AsyncClient=FakeClient))


@pytest.mark.asyncio
async def test_pending_message_completes_then_duplicate_skips_gateway(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_case: RabbitCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = make_payment()
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        await uow.payments.add(payment)
        await uow.commit()

    gateway = CountingGateway()
    notifier = CountingNotifier()
    configure_test_handler(monkeypatch, session_factory, gateway, notifier)
    register_test_payment_subscriber(rabbit_case)
    await rabbit_case.broker.start()
    await rabbit_case.broker.publish(
        {"payment_id": str(payment.id)},
        routing_key=rabbit_case.source.routing_key,
        exchange=rabbit_case.exchange,
        persist=True,
    )
    await wait_for(lambda: notifier.calls == 1)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        stored = await uow.payments.get_by_id(payment.id)
    assert stored is not None and stored.status is PaymentStatus.SUCCEEDED
    assert stored.processed_at is not None and stored.processed_at.utcoffset().total_seconds() == 0
    assert gateway.calls == 1

    await rabbit_case.broker.publish(
        {"payment_id": str(payment.id)},
        routing_key=rabbit_case.source.routing_key,
        exchange=rabbit_case.exchange,
        persist=True,
    )
    await wait_for(lambda: notifier.calls == 2)
    assert gateway.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("webhook_status", "expected_attempts"), [(503, 3), (400, 1)])
async def test_webhook_failure_dead_letters_original_message(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_case: RabbitCase,
    monkeypatch: pytest.MonkeyPatch,
    webhook_status: int,
    expected_attempts: int,
) -> None:
    payment = make_payment()
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        await uow.payments.add(payment)
        await uow.commit()

    attempts = 0

    def fail_webhook(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(webhook_status)

    gateway = CountingGateway()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail_webhook)) as client:
        notifier = HTTPWebhookNotifier(client, base_delay_seconds=0.01)
        configure_test_handler(monkeypatch, session_factory, gateway, notifier)
        register_test_payment_subscriber(rabbit_case)
        await rabbit_case.broker.start()
        body = {"payment_id": str(payment.id)}
        await rabbit_case.broker.publish(
            body,
            routing_key=rabbit_case.source.routing_key,
            exchange=rabbit_case.exchange,
            persist=True,
        )
        dead_body, dead_headers = await asyncio.wait_for(rabbit_case.dead_letters.get(), timeout=5)
        assert json.loads(dead_body) == body
        assert dead_headers["x-death"][0]["reason"] == "rejected"

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        stored = await uow.payments.get_by_id(payment.id)
    assert stored is not None and stored.status is PaymentStatus.SUCCEEDED
    assert gateway.calls == 1
    assert attempts == expected_attempts
