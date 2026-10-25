"""Общий транспортный клиент RabbitMQ для подписчиков модулей."""

from faststream.rabbit import Channel, RabbitBroker

from src.common.configs import get_rabbitmq_config

broker = RabbitBroker(get_rabbitmq_config().url, default_channel=Channel(prefetch_count=1))
