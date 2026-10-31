"""RabbitMQ adapter: топология и обработка сообщений с политикой FastStream."""

from uuid import UUID

import httpx
import structlog
from faststream import AckPolicy
from faststream.exceptions import NackMessage, RejectMessage
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue
from pamqp.commands import Basic

from src.common.configs.rabbitmq_config import (
    PAYMENTS_DLQ,
    PAYMENTS_DLX,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    WEBHOOK_READY_QUEUE,
    WEBHOOK_RETRY_1_QUEUE,
    WEBHOOK_RETRY_2_QUEUE,
)
from src.common.infrastructure.broker import broker
from src.common.infrastructure.database import create_engine, create_session_factory
from src.modules.payments.application.exceptions import PaymentNotFoundError
from src.modules.payments.application.use_cases import ProcessPayment
from src.modules.payments.domain.value_objects import PaymentStatus
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
WEBHOOK_QUEUE = RabbitQueue(
    WEBHOOK_READY_QUEUE,
    durable=True,
    routing_key=WEBHOOK_READY_QUEUE,
    arguments={"x-dead-letter-exchange": PAYMENTS_DLX, "x-dead-letter-routing-key": PAYMENTS_DLQ},
)
RETRY_QUEUES = (
    RabbitQueue(
        WEBHOOK_RETRY_1_QUEUE,
        durable=True,
        routing_key=WEBHOOK_RETRY_1_QUEUE,
        arguments={
            "x-message-ttl": 1000,
            "x-dead-letter-exchange": PAYMENTS_EXCHANGE,
            "x-dead-letter-routing-key": WEBHOOK_READY_QUEUE,
        },
    ),
    RabbitQueue(
        WEBHOOK_RETRY_2_QUEUE,
        durable=True,
        routing_key=WEBHOOK_RETRY_2_QUEUE,
        arguments={
            "x-message-ttl": 2000,
            "x-dead-letter-exchange": PAYMENTS_EXCHANGE,
            "x-dead-letter-routing-key": WEBHOOK_READY_QUEUE,
        },
    ),
)


async def declare_retry_queues(rabbit_broker: RabbitBroker = broker) -> None:
    """Declare delay queues and bind them to the payments exchange."""
    exchange = await rabbit_broker.declare_exchange(NEW_EXCHANGE)
    for queue_config in RETRY_QUEUES:
        queue = await rabbit_broker.declare_queue(queue_config)
        await queue.bind(exchange, routing_key=queue_config.routing_key)
        logger.debug("webhook_retry_queue_declared", queue=queue_config.name)
    logger.info("webhook_retry_topology_ready")


async def publish_webhook_task(payment_id: UUID, attempt: int, routing_key: str) -> None:
    logger.debug("webhook_task_publish_started", payment_id=str(payment_id), attempt=attempt, routing_key=routing_key)
    confirmation = await broker.publish(
        {"payment_id": str(payment_id), "attempt": attempt},
        exchange=PAYMENTS_EXCHANGE,
        routing_key=routing_key,
        mandatory=True,
        persist=True,
        timeout=10.0,
    )
    if not isinstance(confirmation, Basic.Ack):
        raise RuntimeError("Webhook task publication was not confirmed")
    logger.info("webhook_task_published", payment_id=str(payment_id), attempt=attempt, routing_key=routing_key)


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
        await ProcessPayment(lambda: SQLAlchemyPaymentUnitOfWork(session_factory), SimulatedPaymentGateway()).execute(
            payment_id
        )
    except PaymentNotFoundError:
        logger.warning("payment_message_unknown_payment", payment_id=str(payment_id))
        raise RejectMessage(requeue=False) from None
    except Exception as error:
        logger.error("payment_message_processing_failed", payment_id=str(payment_id), error_type=type(error).__name__)
        # Ошибки БД и шлюза возвращают сообщение без лимита повторов.
        # При постоянном сбое оно будет обрабатываться снова, пока причина не устранена.
        raise NackMessage(requeue=True) from error

    try:
        await publish_webhook_task(payment_id, 1, WEBHOOK_READY_QUEUE)
    except Exception as error:
        logger.error("webhook_handoff_failed", payment_id=str(payment_id), error_type=type(error).__name__)
        raise NackMessage(requeue=True) from error
    logger.info("payment_message_acknowledged", payment_id=str(payment_id))


@broker.subscriber(WEBHOOK_QUEUE, NEW_EXCHANGE, ack_policy=AckPolicy.REJECT_ON_ERROR)
async def handle_webhook(payload: dict[str, object]) -> None:
    """Отправить один webhook и запланировать следующую попытку при временном сбое."""
    try:
        payment_id = UUID(str(payload["payment_id"]))
        attempt = payload["attempt"]
        if type(attempt) is not int or not 1 <= attempt <= 3:
            raise ValueError("Invalid attempt")
    except (ValueError, TypeError, KeyError) as error:
        logger.warning("webhook_message_invalid", error_type=type(error).__name__)
        raise RejectMessage(requeue=False) from error

    logger.debug("webhook_message_received", payment_id=str(payment_id), attempt=attempt)
    try:
        async with SQLAlchemyPaymentUnitOfWork(session_factory) as uow:
            payment = await uow.payments.get_by_id(payment_id)
    except Exception as error:
        logger.error("webhook_payment_read_failed", payment_id=str(payment_id), error_type=type(error).__name__)
        raise NackMessage(requeue=True) from error
    if payment is None:
        logger.warning("webhook_payment_not_found", payment_id=str(payment_id))
        raise RejectMessage(requeue=False)
    if payment.status is PaymentStatus.PENDING:
        logger.warning("webhook_payment_not_final", payment_id=str(payment_id))
        raise RejectMessage(requeue=False)

    try:
        async with httpx.AsyncClient() as client:
            result = await HTTPWebhookNotifier(client).notify(payment)
    except Exception as error:
        logger.error(
            "webhook_attempt_failed", payment_id=str(payment_id), attempt=attempt, error_type=type(error).__name__
        )
        raise NackMessage(requeue=True) from error

    if result == "success":
        logger.info("webhook_message_acknowledged", payment_id=str(payment_id), attempt=attempt)
        return
    if result == "permanent_failure" or attempt == 3:
        logger.warning("webhook_message_dead_lettered", payment_id=str(payment_id), attempt=attempt)
        raise RejectMessage(requeue=False)
    routing_key = WEBHOOK_RETRY_1_QUEUE if attempt == 1 else WEBHOOK_RETRY_2_QUEUE
    try:
        await publish_webhook_task(payment_id, attempt + 1, routing_key)
    except Exception as error:
        logger.error(
            "webhook_retry_publish_failed", payment_id=str(payment_id), attempt=attempt, error_type=type(error).__name__
        )
        raise NackMessage(requeue=True) from error
    logger.debug("webhook_retry_scheduled", payment_id=str(payment_id), attempt=attempt + 1, routing_key=routing_key)
