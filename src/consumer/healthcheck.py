"""Пассивная проверка топологии, созданной подписчиками consumer."""

import asyncio

import aio_pika
import structlog

from src.common.configs import get_rabbitmq_config
from src.common.configs.rabbitmq_config import PAYMENTS_EXCHANGE, PAYMENTS_NEW_QUEUE
from src.common.logger import setup_logger


async def check() -> None:
    logger = structlog.get_logger(__name__)
    connection = await aio_pika.connect_robust(get_rabbitmq_config().url, timeout=3)
    try:
        async with connection.channel() as channel:
            await channel.declare_exchange(PAYMENTS_EXCHANGE, passive=True)
            await channel.declare_queue(PAYMENTS_NEW_QUEUE, passive=True)
        logger.info("payment_consumer_topology_ready")
    finally:
        await connection.close()


if __name__ == "__main__":
    setup_logger(service_name="consumer-healthcheck")
    asyncio.run(check())
