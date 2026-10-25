"""Асинхронные репозитории платежей и outbox поверх общей сессии."""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.payments.application.interfaces import OutboxRepository, PaymentRepository
from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.domain.value_objects import PaymentStatus
from src.modules.payments.infrastructure.db import models as orm
from src.modules.payments.infrastructure.db.mappers import (
    outbox_to_domain,
    outbox_to_orm,
    payment_to_domain,
    payment_to_orm,
)

logger = structlog.get_logger(__name__)


class SQLAlchemyPaymentRepository(PaymentRepository):
    """Хранение платежей без самостоятельного управления транзакцией."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> None:
        logger.debug("payment_add_started", payment_id=str(payment.id))
        try:
            self._session.add(payment_to_orm(payment))
        except Exception as error:
            logger.error("payment_add_failed", payment_id=str(payment.id), error_type=type(error).__name__)
            raise
        logger.debug("payment_add_staged", payment_id=str(payment.id))

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        logger.debug("payment_get_started", payment_id=str(payment_id))
        try:
            record = await self._session.get(orm.Payment, payment_id)
            result = payment_to_domain(record) if record is not None else None
        except Exception as error:
            logger.error("payment_get_failed", payment_id=str(payment_id), error_type=type(error).__name__)
            raise
        logger.debug("payment_get_completed", payment_id=str(payment_id), found=result is not None)
        return result

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        logger.debug("payment_get_by_idempotency_key_started")
        try:
            result = await self._session.execute(select(orm.Payment).where(orm.Payment.idempotency_key == key))
            record = result.scalar_one_or_none()
            payment = payment_to_domain(record) if record is not None else None
        except Exception as error:
            logger.error("payment_get_by_idempotency_key_failed", error_type=type(error).__name__)
            raise
        logger.debug("payment_get_by_idempotency_key_completed", found=payment is not None)
        return payment

    async def update_status(
        self,
        payment_id: uuid.UUID,
        expected_status: PaymentStatus,
        new_status: PaymentStatus,
        processed_at: datetime | None = None,
    ) -> bool:
        logger.debug(
            "payment_status_update_started",
            payment_id=str(payment_id),
            expected_status=expected_status.value,
            new_status=new_status.value,
        )
        try:
            values: dict[str, PaymentStatus | datetime] = {"status": new_status}
            if processed_at is not None:
                values["processed_at"] = processed_at
            result = await self._session.execute(
                update(orm.Payment)
                .where(orm.Payment.id == payment_id, orm.Payment.status == expected_status)
                .values(**values)
                .returning(orm.Payment.id)
            )
            updated = result.scalar_one_or_none() is not None
        except Exception as error:
            logger.error("payment_status_update_failed", payment_id=str(payment_id), error_type=type(error).__name__)
            raise
        logger.debug("payment_status_update_completed", payment_id=str(payment_id), updated=updated)
        return updated


class SQLAlchemyOutboxRepository(OutboxRepository):
    """Хранение событий outbox без самостоятельного управления транзакцией."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEvent) -> None:
        logger.debug("outbox_add_started", event_id=str(event.id))
        try:
            self._session.add(outbox_to_orm(event))
        except Exception as error:
            logger.error("outbox_add_failed", event_id=str(event.id), error_type=type(error).__name__)
            raise
        logger.debug("outbox_add_staged", event_id=str(event.id))

    async def get_by_id(self, event_id: uuid.UUID) -> OutboxEvent | None:
        logger.debug("outbox_get_started", event_id=str(event_id))
        try:
            record = await self._session.get(orm.OutboxEvent, event_id)
            result = outbox_to_domain(record) if record is not None else None
        except Exception as error:
            logger.error("outbox_get_failed", event_id=str(event_id), error_type=type(error).__name__)
            raise
        logger.debug("outbox_get_completed", event_id=str(event_id), found=result is not None)
        return result

    async def list_pending(self) -> list[OutboxEvent]:
        logger.debug("outbox_list_started")
        try:
            result = await self._session.execute(
                select(orm.OutboxEvent).order_by(orm.OutboxEvent.created_at)
            )
            events = [outbox_to_domain(record) for record in result.scalars()]
        except Exception as error:
            logger.error("outbox_list_failed", error_type=type(error).__name__)
            raise
        logger.debug("outbox_list_completed", count=len(events))
        return events

    async def delete(self, event_id: uuid.UUID) -> bool:
        logger.debug("outbox_delete_started", event_id=str(event_id))
        try:
            result = await self._session.execute(
                delete(orm.OutboxEvent).where(orm.OutboxEvent.id == event_id).returning(orm.OutboxEvent.id)
            )
            deleted = result.scalar_one_or_none() is not None
        except Exception as error:
            logger.error("outbox_delete_failed", event_id=str(event_id), error_type=type(error).__name__)
            raise
        logger.debug("outbox_delete_completed", event_id=str(event_id), deleted=deleted)
        return deleted
