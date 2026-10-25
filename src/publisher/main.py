"""Запуск outbox publisher: `python -m src.publisher.main`."""

import asyncio

import structlog

from src.common.infrastructure.broker import broker
from src.common.infrastructure.database import create_engine, create_session_factory
from src.common.logger import setup_logger
from src.modules.payments.application.use_cases import RelayOutbox
from src.modules.payments.infrastructure.publisher import RabbitOutboxPublisher
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork

POLL_INTERVAL_SECONDS = 1.0


async def run() -> None:
    setup_logger(service_name="publisher")
    logger = structlog.get_logger(__name__)
    engine = create_engine()
    session_factory = create_session_factory(engine)
    relay = RelayOutbox(lambda: SQLAlchemyPaymentUnitOfWork(session_factory), RabbitOutboxPublisher(broker))

    try:
        await broker.connect()
        logger.info("outbox_publisher_started")
        while True:
            try:
                await relay.execute()
            except Exception as error:
                logger.error("outbox_relay_poll_failed", error_type=type(error).__name__)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await broker.stop()
        await engine.dispose()
        logger.info("outbox_publisher_stopped")


if __name__ == "__main__":
    asyncio.run(run())
