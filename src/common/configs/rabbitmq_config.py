"""Настройки соединения consumer с RabbitMQ."""

from urllib.parse import quote

from pydantic import Field, SecretStr

from src.common.configs.common import CommonConfig

PAYMENTS_EXCHANGE = "payments"
PAYMENTS_NEW_QUEUE = "payments.new"
PAYMENTS_DLX = "payments.dlx"
PAYMENTS_DLQ = "payments.dead_letter"


class RabbitMQConfig(CommonConfig):
    host: str = Field(default="localhost", validation_alias="RABBITMQ_HOST")
    port: int = Field(default=5672, validation_alias="RABBITMQ_PORT")
    user: str = Field(default="guest", validation_alias="RABBITMQ_USER")
    password: SecretStr = Field(default=SecretStr("guest"), validation_alias="RABBITMQ_PASSWORD")
    vhost: str = Field(default="/", validation_alias="RABBITMQ_VHOST")

    @property
    def url(self) -> str:
        user = quote(self.user, safe="")
        password = quote(self.password.get_secret_value(), safe="")
        vhost = quote(self.vhost, safe="")
        return f"amqp://{user}:{password}@{self.host}:{self.port}/{vhost}"
