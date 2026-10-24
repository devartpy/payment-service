"""Преобразование доменных сущностей платежа и outbox в ORM и обратно."""

import structlog

from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.infrastructure.db import models as orm

logger = structlog.get_logger(__name__)


def payment_to_orm(payment: Payment) -> orm.Payment:
    """Создать ORM-строку для нового платежа."""
    logger.debug("payment_mapping_started", direction="to_orm", payment_id=str(payment.id))
    try:
        result = orm.Payment(
            id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata_json=dict(payment.metadata_json),
            status=payment.status,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
        )
    except Exception as error:
        logger.error(
            "payment_mapping_failed", direction="to_orm", payment_id=str(payment.id), error_type=type(error).__name__
        )
        raise
    logger.debug("payment_mapping_completed", direction="to_orm", payment_id=str(payment.id))
    return result


def payment_to_domain(payment: orm.Payment) -> Payment:
    """Восстановить доменную сущность из ORM-строки."""
    logger.debug("payment_mapping_started", direction="to_domain", payment_id=str(payment.id))
    try:
        result = Payment(
            id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata_json=dict(payment.metadata_json),
            status=payment.status,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
        )
    except Exception as error:
        logger.error(
            "payment_mapping_failed", direction="to_domain", payment_id=str(payment.id), error_type=type(error).__name__
        )
        raise
    logger.debug("payment_mapping_completed", direction="to_domain", payment_id=str(payment.id))
    return result


def outbox_to_orm(event: OutboxEvent) -> orm.OutboxEvent:
    """Создать ORM-строку для нового события."""
    logger.debug("outbox_mapping_started", direction="to_orm", event_id=str(event.id))
    try:
        result = orm.OutboxEvent(
            id=event.id,
            event_type=event.event_type,
            payload=dict(event.payload),
            created_at=event.created_at,
        )
    except Exception as error:
        logger.error(
            "outbox_mapping_failed", direction="to_orm", event_id=str(event.id), error_type=type(error).__name__
        )
        raise
    logger.debug("outbox_mapping_completed", direction="to_orm", event_id=str(event.id))
    return result


def outbox_to_domain(event: orm.OutboxEvent) -> OutboxEvent:
    """Восстановить доменное событие из ORM-строки."""
    logger.debug("outbox_mapping_started", direction="to_domain", event_id=str(event.id))
    try:
        result = OutboxEvent(
            id=event.id,
            event_type=event.event_type,
            payload=dict(event.payload),
            created_at=event.created_at,
        )
    except Exception as error:
        logger.error(
            "outbox_mapping_failed", direction="to_domain", event_id=str(event.id), error_type=type(error).__name__
        )
        raise
    logger.debug("outbox_mapping_completed", direction="to_domain", event_id=str(event.id))
    return result
