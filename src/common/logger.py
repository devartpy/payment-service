"""Единый вывод логов приложения и стандартного logging в stdout."""

import logging
import sys
import uuid
from typing import Any

import structlog

from src.common.configs import get_logger_config


def get_default_trace_id() -> str:
    """Возвращает дефолтный trace_id для логов, если он не был установлен в контексте."""
    return str(uuid.uuid4())


def setup_logger(service_name: str) -> None:
    """Настроить логирование процесса с именем его точки запуска."""
    if not service_name.strip():
        raise ValueError("service_name must not be empty")

    config = get_logger_config()
    log_level = getattr(logging, config.log_level.upper(), None)
    if not isinstance(log_level, int):
        raise ValueError(f"Invalid APP_LOG_LEVEL: {config.log_level!r}")

    def add_service_name(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict["service"] = service_name
        return event_dict

    exception_processor = (
        structlog.processors.ExceptionRenderer(structlog.tracebacks.ExceptionDictTransformer(show_locals=False))
        if config.json_logs
        else structlog.processors.format_exc_info
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service_name,
        structlog.processors.StackInfoRenderer(),
        exception_processor,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if config.json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Этот шаблон управляет корневым обработчиком процесса. force=True не
    # накапливает обработчики при повторной настройке.
    logging.basicConfig(level=log_level, handlers=[handler], force=True)

    # Uvicorn устанавливает собственные обработчики; направляем его записи
    # через root, чтобы все строки имели один формат.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        framework_logger = logging.getLogger(logger_name)
        for existing_handler in framework_logger.handlers[:]:
            framework_logger.removeHandler(existing_handler)
            existing_handler.close()
        framework_logger.propagate = True
