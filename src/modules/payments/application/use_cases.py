"""Сценарии создания и чтения платежей."""

from collections.abc import Callable
from uuid import UUID

import structlog

from src.common.exceptions import ApplicationException
from src.modules.payments.application.dtos import CreatePaymentCommand
from src.modules.payments.application.exceptions import IdempotencyConflictError, PaymentNotFoundError
from src.modules.payments.application.interfaces import PaymentUnitOfWork
from src.modules.payments.domain.exceptions import PaymentDomainException
from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.domain.value_objects import OutboxEventType

logger = structlog.get_logger(__name__)


class CreatePayment:
    def __init__(self, uow_factory: Callable[[], PaymentUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: CreatePaymentCommand) -> Payment:
        logger.debug("payment_create_started")
        try:
            async with self._uow_factory() as uow:
                existing = await uow.payments.get_by_idempotency_key(command.idempotency_key)
                if existing is not None:
                    logger.warning("payment_idempotency_conflict", payment_id=str(existing.id))
                    raise IdempotencyConflictError()

                payment = Payment(
                    amount=command.amount,
                    currency=command.currency,
                    description=command.description,
                    metadata_json=command.metadata_json,
                    webhook_url=command.webhook_url,
                    idempotency_key=command.idempotency_key,
                )
                event = OutboxEvent(
                    event_type=OutboxEventType.PAYMENT_NEW,
                    payload=payment.new_event_payload(),
                )
                logger.debug("payment_create_staging", payment_id=str(payment.id), event_id=str(event.id))
                await uow.payments.add(payment)
                await uow.outbox.add(event)
                await uow.commit()
        except PaymentDomainException as error:
            logger.warning("payment_domain_rejected", code=error.code)
            message = {
                "PAYMENT_AMOUNT_TOO_LOW": "Некорректная сумма платежа",
                "INVALID_WEBHOOK_URL": "Некорректный URL",
            }.get(error.code, "Некорректные данные платежа")
            raise ApplicationException(message, error.code) from error
        except ApplicationException:
            raise
        except Exception as error:
            logger.error("payment_create_failed", error_type=type(error).__name__)
            raise

        logger.info("payment_created", payment_id=str(payment.id))
        return payment


class GetPayment:
    def __init__(self, uow_factory: Callable[[], PaymentUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, payment_id: UUID) -> Payment:
        logger.debug("payment_get_started", payment_id=str(payment_id))
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_id(payment_id)
        if payment is None:
            logger.warning("payment_not_found", payment_id=str(payment_id))
            raise PaymentNotFoundError()
        logger.info("payment_get_completed", payment_id=str(payment_id))
        return payment
