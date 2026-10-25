"""RabbitMQ adapter: топология и обработка сообщений с политикой FastStream."""

from uuid import UUID

import httpx
import structlog
from faststream import AckPolicy
from faststream.exceptions import NackMessage, RejectMessage
from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue

from src.common.configs.rabbitmq_config import (
    PAYMENTS_DLQ,
    PAYMENTS_DLX,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
)
from src.common.infrastructure.broker import broker
from src.common.infrastructure.database import create_engine, create_session_factory
from src.modules.payments.application.exceptions import PaymentNotFoundError
from src.modules.payments.application.use_cases import ProcessPayment
from src.modules.payments.infrastructure.gateway import SimulatedPaymentGateway
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork
from src.modules.payments.infrastructure.webhook import HTTPWebhookNotifier

logger = structlog.get_logger(__name__)

# SQLAlchemy создаёт соединения по требованию; один engine обслуживает весь процесс consumer.
engine = create_engine()
session_factory = create_session_factory(engine)

NEW_EXCHANGE = RabbitExchange(PAYMENTS_EXCHANGE, type=ExchangeType.DIRECT, durable=True)
DLX_EXCHANGE = RabbitExchange(PAYMENTS_DLX, type=ExchangeType.DIRECT, durable=True)
DLQ_QUEUE = RabbitQueue(PAYMENTS_DLQ, durable=True, routing_key=PAYMENTS_DLQ)
NEW_QUEUE = RabbitQueue(
    PAYMENTS_NEW_QUEUE,
    durable=True,
    routing_key=PAYMENTS_NEW_QUEUE,
    arguments={
        "x-dead-letter-exchange": PAYMENTS_DLX,
        "x-dead-letter-routing-key": PAYMENTS_DLQ,
        "x-single-active-consumer": True,
    },
)


@broker.subscriber(DLQ_QUEUE, DLX_EXCHANGE, ack_policy=AckPolicy.ACK)
async def handle_failed_payments_dlq(payload: dict[str, object]) -> None:
    """Зафиксировать ошибку доставки; FastStream подтвердит сообщение."""
    logger.critical("payment_dead_letter_received", payment_id=str(payload.get("payment_id")))


@broker.subscriber(NEW_QUEUE, NEW_EXCHANGE, ack_policy=AckPolicy.REJECT_ON_ERROR)
async def handle_payment(payload: dict[str, object]) -> None:
    """Обработать платёж; исключения управляют подтверждением RabbitMQ."""
    try:
        payment_id = UUID(str(payload["payment_id"]))
    except (ValueError, TypeError, KeyError) as error:
        logger.warning("payment_message_invalid", error_type=type(error).__name__)
        raise RejectMessage(requeue=False) from error

    logger.debug("payment_message_received", payment_id=str(payment_id))
    try:
        payment = await ProcessPayment(
            lambda: SQLAlchemyPaymentUnitOfWork(session_factory), SimulatedPaymentGateway()
        ).execute(payment_id)
    except PaymentNotFoundError:
        logger.warning("payment_message_unknown_payment", payment_id=str(payment_id))
        raise RejectMessage(requeue=False) from None
    except Exception as error:
        logger.error("payment_message_processing_failed", payment_id=str(payment_id), error_type=type(error).__name__)
        # Ошибки БД и шлюза возвращают сообщение без лимита повторов.
        # При постоянном сбое оно будет обрабатываться снова, пока причина не устранена.
        raise NackMessage(requeue=True) from error

    if payment is None:
        raise NackMessage(requeue=True)

    async with httpx.AsyncClient() as client:
        try:
            delivered = await HTTPWebhookNotifier(client).notify(payment)
        except Exception as error:
            logger.error(
                "payment_message_processing_failed", payment_id=str(payment_id), error_type=type(error).__name__
            )
            raise NackMessage(requeue=True) from error

    if delivered:
        logger.info("payment_message_acknowledged", payment_id=str(payment_id))
        return
    logger.warning("payment_message_dead_lettered", payment_id=str(payment_id))
    raise RejectMessage(requeue=False)
