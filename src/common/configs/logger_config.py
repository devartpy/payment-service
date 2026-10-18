from pydantic import Field

from src.common.configs.common import CommonConfig


class LoggerConfig(CommonConfig):
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    json_logs: bool = Field(default=True, validation_alias="APP_JSON_LOGS")
