"""Проверки границ транзакции платежей и outbox на PostgreSQL."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.domain.value_objects import Currency, OutboxEventType, PaymentStatus
from src.modules.payments.infrastructure.db import models as orm
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork


def make_payment(key: str | None = None) -> Payment:
    return Payment(
        amount=Decimal("123.45"),
        currency=Currency.RUB,
        description="Integration test payment",
        idempotency_key=key or str(uuid.uuid4()),
        webhook_url="https://merchant.example/webhook",
        metadata_json={"order_id": "test-order"},
    )


def make_event(payment: Payment, event_id: uuid.UUID | None = None) -> OutboxEvent:
    return OutboxEvent(
        id=event_id,
        event_type=OutboxEventType.PAYMENT_NEW,
        payload={"payment_id": str(payment.id)},
    )


async def counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with factory() as session:
        payment_count = await session.scalar(select(func.count()).select_from(orm.Payment))
        outbox_count = await session.scalar(select(func.count()).select_from(orm.OutboxEvent))
    return int(payment_count or 0), int(outbox_count or 0)


@pytest.mark.asyncio
async def test_payment_and_outbox_are_visible_together_only_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    event = make_event(payment)
    uow = SQLAlchemyPaymentUnitOfWork(session_factory)

    async with uow as transaction:
        await transaction.payments.add(payment)
        await transaction.outbox.add(event)
        assert await counts(session_factory) == (0, 0)
        await transaction.commit()

    assert await counts(session_factory) == (1, 1)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        stored_payment = await transaction.payments.get_by_id(payment.id)
        stored_by_key = await transaction.payments.get_by_idempotency_key(payment.idempotency_key)
        stored_event = await transaction.outbox.get_by_id(event.id)

    assert stored_payment is not None
    assert stored_by_key is not None
    assert stored_event is not None
    assert stored_payment.id == stored_by_key.id == payment.id
    assert stored_payment.amount == payment.amount
    assert stored_payment.currency == payment.currency
    assert stored_payment.metadata_json == payment.metadata_json
    assert stored_payment.status is PaymentStatus.NEW
    assert stored_payment.created_at.tzinfo is not None
    assert stored_payment.created_at.utcoffset().total_seconds() == 0
    assert stored_event.payload == event.payload
    assert stored_event.event_type is OutboxEventType.PAYMENT_NEW
    assert stored_event.created_at.tzinfo is not None
    assert stored_event.created_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_clean_exit_without_commit_does_not_persist_payment_or_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        await transaction.payments.add(payment)
        await transaction.outbox.add(make_event(payment))

    assert await counts(session_factory) == (0, 0)


@pytest.mark.asyncio
async def test_failed_outbox_insert_rolls_back_new_payment(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_payment = make_payment()
    first_event = make_event(first_payment)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        await transaction.payments.add(first_payment)
        await transaction.outbox.add(first_event)
        await transaction.commit()

    second_payment = make_payment()
    duplicate_event = make_event(second_payment, event_id=first_event.id)
    with pytest.raises(IntegrityError):
        async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
            await transaction.payments.add(second_payment)
            await transaction.outbox.add(duplicate_event)
            await transaction.commit()

    assert await counts(session_factory) == (1, 1)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        assert await transaction.payments.get_by_id(second_payment.id) is None


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_does_not_create_second_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key = str(uuid.uuid4())
    first_payment = make_payment(key)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        await transaction.payments.add(first_payment)
        await transaction.outbox.add(make_event(first_payment))
        await transaction.commit()

    duplicate_payment = make_payment(key)
    with pytest.raises(IntegrityError):
        async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
            await transaction.payments.add(duplicate_payment)
            await transaction.outbox.add(make_event(duplicate_payment))
            await transaction.commit()

    assert await counts(session_factory) == (1, 1)


@pytest.mark.asyncio
async def test_status_change_and_outbox_delete_share_rollback_and_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    event = make_event(payment)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        await transaction.payments.add(payment)
        await transaction.outbox.add(event)
        await transaction.commit()

    with pytest.raises(RuntimeError, match="publisher failed"):
        async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
            assert await transaction.payments.update_status(payment.id, PaymentStatus.NEW, PaymentStatus.PENDING)
            assert await transaction.outbox.delete(event.id)
            raise RuntimeError("publisher failed")

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        stored_payment = await transaction.payments.get_by_id(payment.id)
        stored_event = await transaction.outbox.get_by_id(event.id)
    assert stored_payment is not None and stored_payment.status is PaymentStatus.NEW
    assert stored_event is not None

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        assert await transaction.payments.update_status(payment.id, PaymentStatus.NEW, PaymentStatus.PENDING)
        assert await transaction.outbox.delete(event.id)
        await transaction.commit()

    assert await counts(session_factory) == (1, 0)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        stored_payment = await transaction.payments.get_by_id(payment.id)
        assert not await transaction.payments.update_status(payment.id, PaymentStatus.NEW, PaymentStatus.PENDING)
        assert not await transaction.outbox.delete(event.id)
    assert stored_payment is not None and stored_payment.status is PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_processed_at_round_trips_with_utc_offset(session_factory: async_sessionmaker[AsyncSession]) -> None:
    payment = make_payment()
    processed_at = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        await transaction.payments.add(payment)
        await transaction.commit()

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        assert await transaction.payments.update_status(
            payment.id, PaymentStatus.NEW, PaymentStatus.SUCCEEDED, processed_at
        )
        await transaction.commit()

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        stored_payment = await transaction.payments.get_by_id(payment.id)
    assert stored_payment is not None
    assert stored_payment.processed_at == processed_at


@pytest.mark.asyncio
async def test_status_update_without_timestamp_preserves_existing_processed_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    processed_at = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        await transaction.payments.add(payment)
        await transaction.commit()

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        assert await transaction.payments.update_status(
            payment.id, PaymentStatus.NEW, PaymentStatus.SUCCEEDED, processed_at
        )
        await transaction.commit()

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        assert await transaction.payments.update_status(payment.id, PaymentStatus.SUCCEEDED, PaymentStatus.SUCCEEDED)
        await transaction.commit()

    async with SQLAlchemyPaymentUnitOfWork(session_factory) as transaction:
        stored_payment = await transaction.payments.get_by_id(payment.id)
    assert stored_payment is not None
    assert stored_payment.processed_at == processed_at
