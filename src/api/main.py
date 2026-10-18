"""Точка входа HTTP-процесса для Uvicorn: src.api.main:app."""

from src.api.app import create_app
from src.api.middlewares import TraceIdMiddleware
from src.common.logger import setup_logger

setup_logger(service_name="api")
app = TraceIdMiddleware(create_app())
