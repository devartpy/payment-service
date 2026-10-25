"""Outbox relay на временной схеме текущего PostgreSQL и уникальной топологии RabbitMQ."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import aio_pika
import pytest
from aio_pika.abc import AbstractQueue
from faststream.rabbit import Channel, RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.configs import get_rabbitmq_config
from src.consumer import healthcheck
from src.modules.payments.application.use_cases import RelayOutbox
from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.domain.value_objects import Currency, OutboxEventType, PaymentStatus
from src.modules.payments.infrastructure import publisher as publisher_module
from src.modules.payments.infrastructure.publisher import RabbitOutboxPublisher
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork


@pytest.fixture
async def rabbit_topology(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[RabbitBroker, AbstractQueue]]:
    suffix = uuid4().hex
    exchange_name = f"test.payments.{suffix}"
    queue_name = f"test.payments.new.{suffix}"
    connection = await aio_pika.connect_robust(get_rabbitmq_config().url)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(exchange_name, durable=True)
    queue = await channel.declare_queue(queue_name, durable=True)
    await queue.bind(exchange, routing_key=queue_name)
    monkeypatch.setattr(publisher_module, "PAYMENTS_EXCHANGE", exchange_name)
    monkeypatch.setattr(publisher_module, "PAYMENTS_NEW_QUEUE", queue_name)
    broker = RabbitBroker(
        get_rabbitmq_config().url,
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
    )
    await broker.connect()
    try:
        yield broker, queue
    finally:
        await broker.stop()
        await queue.delete(if_unused=False, if_empty=False)
        await exchange.delete(if_unused=False)
        await connection.close()


def make_pair(*, created_at: datetime | None = None, event_id: UUID | None = None) -> tuple[Payment, OutboxEvent]:
    payment = Payment(
        amount=Decimal("12.50"),
        currency=Currency.RUB,
        description="Outbox relay test",
        idempotency_key=uuid4().hex,
        webhook_url="https://merchant.example/hook",
    )
    event = OutboxEvent(
        OutboxEventType.PAYMENT_NEW,
        payment.new_event_payload(),
        id=event_id,
        created_at=created_at,
    )
    return payment, event


async def save_pair(factory: async_sessionmaker[AsyncSession], payment: Payment, event: OutboxEvent) -> None:
    async with SQLAlchemyPaymentUnitOfWork(factory) as uow:
        await uow.payments.add(payment)
        await uow.outbox.add(event)
        await uow.commit()


@pytest.mark.asyncio
async def test_relay_reads_in_order_and_commits_deletions_individually(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_topology: tuple[RabbitBroker, AbstractQueue],
) -> None:
    broker, queue = rabbit_topology
    timestamp = datetime.now(timezone.utc) - timedelta(minutes=1)
    later_payment, later = make_pair(created_at=timestamp + timedelta(seconds=1))
    first_payment, first = make_pair(created_at=timestamp, event_id=UUID(int=1))
    second_payment, second = make_pair(created_at=timestamp + timedelta(microseconds=1), event_id=UUID(int=2))
    for payment, event in ((later_payment, later), (second_payment, second), (first_payment, first)):
        await save_pair(session_factory, payment, event)

    relay = RelayOutbox(lambda: SQLAlchemyPaymentUnitOfWork(session_factory), RabbitOutboxPublisher(broker))
    assert await relay.execute() == 3
    messages = [await queue.get(no_ack=True, timeout=3) for _ in range(3)]
    assert [message.message_id for message in messages] == [str(first.id), str(second.id), str(later.id)]
    assert [json.loads(message.body) for message in messages] == [
        first.payload,
        second.payload,
        later.payload,
    ]
    assert all(message.delivery_mode is aio_pika.DeliveryMode.PERSISTENT for message in messages)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        assert await uow.outbox.list_pending() == []
        stored_payment = await uow.payments.get_by_id(first_payment.id)
        assert stored_payment is not None and stored_payment.status is PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_new_insert_is_processed_on_next_poll(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_topology: tuple[RabbitBroker, AbstractQueue],
) -> None:
    broker, queue = rabbit_topology
    first_payment, first = make_pair()
    second_payment, second = make_pair()
    await save_pair(session_factory, first_payment, first)

    class InsertOnPublish:
        async def publish(self, event: OutboxEvent) -> None:
            await RabbitOutboxPublisher(broker).publish(event)
            if event.id == first.id:
                await save_pair(session_factory, second_payment, second)

    relay = RelayOutbox(lambda: SQLAlchemyPaymentUnitOfWork(session_factory), InsertOnPublish())
    assert await relay.execute() == 1
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        assert [event.id for event in await uow.outbox.list_pending()] == [second.id]
    assert await relay.execute() == 1
    assert [json.loads((await queue.get(no_ack=True, timeout=3)).body) for _ in range(2)] == [
        first.payload,
        second.payload,
    ]


@pytest.mark.asyncio
async def test_commit_failure_republishes_event(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_topology: tuple[RabbitBroker, AbstractQueue],
) -> None:
    broker, queue = rabbit_topology
    payment, event = make_pair()
    await save_pair(session_factory, payment, event)
    fail = True

    class FailingCommitUoW(SQLAlchemyPaymentUnitOfWork):
        async def commit(self) -> None:
            nonlocal fail
            if fail:
                fail = False
                raise RuntimeError("simulated commit failure")
            await super().commit()

    relay = RelayOutbox(lambda: FailingCommitUoW(session_factory), RabbitOutboxPublisher(broker))
    assert await relay.execute() == 0
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        assert await uow.outbox.get_by_id(event.id) is not None
    assert await relay.execute() == 1
    assert [json.loads((await queue.get(no_ack=True, timeout=3)).body) for _ in range(2)] == [
        event.payload,
        event.payload,
    ]


@pytest.mark.asyncio
async def test_missing_route_keeps_event_and_publisher_does_not_create_topology(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_topology: tuple[RabbitBroker, AbstractQueue],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker, queue = rabbit_topology
    payment, event = make_pair()
    await save_pair(session_factory, payment, event)
    monkeypatch.setattr(publisher_module, "PAYMENTS_NEW_QUEUE", f"missing.{uuid4().hex}")
    relay = RelayOutbox(lambda: SQLAlchemyPaymentUnitOfWork(session_factory), RabbitOutboxPublisher(broker))
    assert await relay.execute() == 0
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        assert await uow.outbox.get_by_id(event.id) is not None
    assert await queue.get(no_ack=True, fail=False, timeout=1) is None


@pytest.mark.asyncio
async def test_missing_exchange_keeps_event_and_is_not_declared_by_publisher(
    session_factory: async_sessionmaker[AsyncSession],
    rabbit_topology: tuple[RabbitBroker, AbstractQueue],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker, _queue = rabbit_topology
    payment, event = make_pair()
    await save_pair(session_factory, payment, event)
    missing_exchange = f"missing.exchange.{uuid4().hex}"
    monkeypatch.setattr(publisher_module, "PAYMENTS_EXCHANGE", missing_exchange)
    relay = RelayOutbox(lambda: SQLAlchemyPaymentUnitOfWork(session_factory), RabbitOutboxPublisher(broker))

    assert await relay.execute() == 0
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
        assert await uow.outbox.get_by_id(event.id) is not None
    connection = await aio_pika.connect_robust(get_rabbitmq_config().url)
    try:
        async with connection.channel() as channel:
            with pytest.raises(aio_pika.exceptions.ChannelClosed):
                await channel.declare_exchange(missing_exchange, passive=True)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_consumer_healthcheck_is_passive(
    rabbit_topology: tuple[RabbitBroker, AbstractQueue],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _broker, queue = rabbit_topology
    monkeypatch.setattr(healthcheck, "PAYMENTS_EXCHANGE", publisher_module.PAYMENTS_EXCHANGE)
    monkeypatch.setattr(healthcheck, "PAYMENTS_NEW_QUEUE", queue.name)
    await healthcheck.check()
    monkeypatch.setattr(healthcheck, "PAYMENTS_NEW_QUEUE", f"missing.{uuid4().hex}")
    with pytest.raises(aio_pika.exceptions.ChannelClosed):
        await healthcheck.check()
