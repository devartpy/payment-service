"""Доставка платежа и webhook через изолированную топологию RabbitMQ."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from faststream import AckPolicy
from faststream.rabbit import Channel, ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.configs import get_rabbitmq_config
from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import Currency, PaymentStatus
from src.modules.payments.infrastructure import consumer as consumer_module
from src.modules.payments.infrastructure.consumer import handle_payment, handle_webhook
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

    async def notify(self, _payment: Payment) -> str:
        self.calls += 1
        return "success"


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
    webhook: RabbitQueue
    retries: tuple[RabbitQueue, RabbitQueue]
    dlq: RabbitQueue
    dlx: RabbitExchange


@pytest.fixture
async def rabbit_case() -> AsyncIterator[RabbitCase]:
    suffix = uuid4().hex
    exchange = RabbitExchange(f"test.payments.{suffix}", type=ExchangeType.DIRECT, durable=True)
    dlx = RabbitExchange(f"test.payments.dlx.{suffix}", type=ExchangeType.DIRECT, durable=True)
    source = RabbitQueue(
        f"test.payments.new.{suffix}",
        durable=True,
        routing_key=f"test.payments.new.{suffix}",
        arguments={"x-dead-letter-exchange": dlx.name, "x-dead-letter-routing-key": f"test.payments.dlq.{suffix}"},
    )
    webhook = RabbitQueue(
        f"test.webhook.ready.{suffix}",
        durable=True,
        routing_key=f"test.webhook.ready.{suffix}",
        arguments={"x-dead-letter-exchange": dlx.name, "x-dead-letter-routing-key": f"test.payments.dlq.{suffix}"},
    )
    retries = tuple(
        RabbitQueue(
            f"test.webhook.retry.{index}.{suffix}",
            durable=True,
            routing_key=f"test.webhook.retry.{index}.{suffix}",
            arguments={
                "x-message-ttl": delay,
                "x-dead-letter-exchange": exchange.name,
                "x-dead-letter-routing-key": webhook.routing_key,
            },
        )
        for index, delay in ((1, 100), (2, 200))
    )
    dlq = RabbitQueue(f"test.payments.dlq.{suffix}", durable=True, routing_key=f"test.payments.dlq.{suffix}")
    broker = RabbitBroker(
        get_rabbitmq_config().url,
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
    )
    try:
        yield RabbitCase(broker, exchange, source, webhook, retries, dlq, dlx)
    finally:
        await broker.stop()
        await broker.connect()
        for queue in (source, webhook, *retries, dlq):
            await (await broker.declare_queue(queue)).delete(if_unused=False, if_empty=False)
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


def configure_handlers(
    monkeypatch: pytest.MonkeyPatch,
    rabbit_case: RabbitCase,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: CountingGateway,
    notifier: CountingNotifier | HTTPWebhookNotifier,
) -> None:
    monkeypatch.setattr(consumer_module, "session_factory", session_factory)
    monkeypatch.setattr(consumer_module, "SimulatedPaymentGateway", lambda: gateway)
    monkeypatch.setattr(consumer_module, "HTTPWebhookNotifier", lambda _client: notifier)
    monkeypatch.setattr(consumer_module, "httpx", SimpleNamespace(AsyncClient=FakeClient))
    monkeypatch.setattr(consumer_module, "broker", rabbit_case.broker)
    monkeypatch.setattr(consumer_module, "PAYMENTS_EXCHANGE", rabbit_case.exchange.name)
    monkeypatch.setattr(consumer_module, "WEBHOOK_READY_QUEUE", rabbit_case.webhook.routing_key)
    monkeypatch.setattr(consumer_module, "WEBHOOK_RETRY_1_QUEUE", rabbit_case.retries[0].routing_key)
    monkeypatch.setattr(consumer_module, "WEBHOOK_RETRY_2_QUEUE", rabbit_case.retries[1].routing_key)

    @rabbit_case.broker.subscriber(rabbit_case.source, rabbit_case.exchange, ack_policy=AckPolicy.REJECT_ON_ERROR)
    async def handle_test_payment(payload: dict[str, object]) -> None:
        await handle_payment(payload)

    @rabbit_case.broker.subscriber(rabbit_case.webhook, rabbit_case.exchange, ack_policy=AckPolicy.REJECT_ON_ERROR)
    async def handle_test_webhook(payload: dict[str, object]) -> None:
        await handle_webhook(payload)


async def start_case(rabbit_case: RabbitCase) -> None:
    await rabbit_case.broker.start()
    dlx = await rabbit_case.broker.declare_exchange(rabbit_case.dlx)
    dlq = await rabbit_case.broker.declare_queue(rabbit_case.dlq)
    await dlq.bind(dlx, routing_key=rabbit_case.dlq.routing_key)
    exchange = await rabbit_case.broker.declare_exchange(rabbit_case.exchange)
    for retry in rabbit_case.retries:
        queue = await rabbit_case.broker.declare_queue(retry)
        await queue.bind(exchange, routing_key=retry.routing_key)


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
    gateway, notifier = CountingGateway(), CountingNotifier()
    configure_handlers(monkeypatch, rabbit_case, session_factory, gateway, notifier)
    await start_case(rabbit_case)
    body = {"payment_id": str(payment.id)}
    await rabbit_case.broker.publish(
        body, routing_key=rabbit_case.source.routing_key, exchange=rabbit_case.exchange, persist=True
    )
    await wait_for(lambda: notifier.calls == 1)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        stored = await uow.payments.get_by_id(payment.id)
    assert stored is not None and stored.status is PaymentStatus.SUCCEEDED
    assert stored.processed_at is not None and stored.processed_at.utcoffset().total_seconds() == 0
    assert gateway.calls == 1
    await rabbit_case.broker.publish(
        body, routing_key=rabbit_case.source.routing_key, exchange=rabbit_case.exchange, persist=True
    )
    await wait_for(lambda: notifier.calls == 2)
    assert gateway.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("webhook_status", "expected_attempts"), [(503, 3), (400, 1)])
async def test_webhook_failure_dead_letters_webhook_message(
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
        configure_handlers(monkeypatch, rabbit_case, session_factory, gateway, HTTPWebhookNotifier(client))
        await start_case(rabbit_case)
        await rabbit_case.broker.publish(
            {"payment_id": str(payment.id)},
            routing_key=rabbit_case.source.routing_key,
            exchange=rabbit_case.exchange,
            persist=True,
        )
        queue = await rabbit_case.broker.declare_queue(rabbit_case.dlq)

        async def read_dead_letter():
            while True:
                message = await queue.get(fail=False)
                if message is not None:
                    return message
                await asyncio.sleep(0.05)

        dead_message = await asyncio.wait_for(read_dead_letter(), timeout=5)
        try:
            assert json.loads(dead_message.body) == {"payment_id": str(payment.id), "attempt": expected_attempts}
            assert dead_message.headers["x-death"][0]["reason"] == "rejected"
        finally:
            await dead_message.ack()
    assert gateway.calls == 1
    assert attempts == expected_attempts
