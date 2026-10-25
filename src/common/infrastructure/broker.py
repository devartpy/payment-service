"""Транспортный клиент RabbitMQ для consumer и publisher."""

from faststream.rabbit import Channel, RabbitBroker

from src.common.configs import get_rabbitmq_config

broker = RabbitBroker(
    get_rabbitmq_config().url,
    default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
)
