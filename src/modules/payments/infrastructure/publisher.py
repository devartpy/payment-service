"""Адаптер публикации outbox в уже созданную consumer топологию."""

import structlog
from faststream.rabbit import RabbitBroker
from pamqp.commands import Basic

from src.common.configs.rabbitmq_config import PAYMENTS_EXCHANGE, PAYMENTS_NEW_QUEUE
from src.modules.payments.application.interfaces import OutboxPublisher
from src.modules.payments.domain.models import OutboxEvent

logger = structlog.get_logger(__name__)
PUBLISH_TIMEOUT_SECONDS = 10.0


class RabbitOutboxPublisher(OutboxPublisher):
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish(self, event: OutboxEvent) -> None:
        logger.debug("outbox_publish_started", event_id=str(event.id))
        try:
            confirmation = await self._broker.publish(
                event.payload,
                exchange=PAYMENTS_EXCHANGE,
                routing_key=PAYMENTS_NEW_QUEUE,
                mandatory=True,
                persist=True,
                timeout=PUBLISH_TIMEOUT_SECONDS,
                message_id=str(event.id),
            )
        except Exception as error:
            logger.error("outbox_publish_failed", event_id=str(event.id), error_type=type(error).__name__)
            raise
        if not isinstance(confirmation, Basic.Ack):
            logger.warning(
                "outbox_publish_not_confirmed",
                event_id=str(event.id),
                confirmation_type=type(confirmation).__name__,
            )
            raise RuntimeError("RabbitMQ did not confirm outbox publication")
        logger.info("outbox_publish_confirmed", event_id=str(event.id))
