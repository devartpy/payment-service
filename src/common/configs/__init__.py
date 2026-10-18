from functools import lru_cache

from .db_config import DatabaseConfig
from .fastapi_config import FastAPIConfig
from .logger_config import LoggerConfig


@lru_cache(maxsize=1)
def get_logger_config() -> LoggerConfig:
    return LoggerConfig()


@lru_cache(maxsize=1)
def get_db_config() -> DatabaseConfig:
    return DatabaseConfig()


@lru_cache(maxsize=1)
def get_fastapi_config() -> FastAPIConfig:
    return FastAPIConfig()


__all__ = [
    "get_db_config",
    "get_fastapi_config",
    "get_logger_config",
]
