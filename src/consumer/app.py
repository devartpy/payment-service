"""FastStream runtime для подписчиков предметных модулей."""

import structlog
from faststream import FastStream
from faststream.rabbit import RabbitBroker

from src.common.infrastructure.broker import broker
from src.common.logger import setup_logger
from src.modules.payments.infrastructure import consumer as payment_consumer

setup_logger(service_name="consumer")
logger = structlog.get_logger(__name__)


def create_consumer_app(rabbit_broker: RabbitBroker) -> FastStream:
    """Собрать runtime; импорт модуля регистрирует его подписку на общем broker."""
    faststream_app = FastStream(rabbit_broker)

    @faststream_app.on_startup
    async def startup_event() -> None:
        logger.info(
            "payment_consumer_starting",
            queues=(
                payment_consumer.NEW_QUEUE.name,
                payment_consumer.WEBHOOK_QUEUE.name,
                payment_consumer.DLQ_QUEUE.name,
            ),
        )
        await rabbit_broker.connect()
        await payment_consumer.declare_dead_letter_queue(rabbit_broker)
        await payment_consumer.declare_retry_queues(rabbit_broker)

    @faststream_app.on_shutdown
    async def shutdown_event() -> None:
        await payment_consumer.engine.dispose()
        logger.info("payment_consumer_shutdown_completed")

    return faststream_app


app = create_consumer_app(broker)
