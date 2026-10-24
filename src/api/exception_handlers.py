"""Единый безопасный формат ошибок HTTP API."""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.common.exceptions import ApplicationException

logger = structlog.get_logger(__name__)


def _response(status_code: int, code: str, message: str, meta: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "meta": meta or {}}},
    )


async def application_exception_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ApplicationException):
        raise error
    logger.warning("application_error", code=error.code, status_code=error.status_code)
    return _response(error.status_code, error.code, error.message, error.meta)


async def http_exception_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, HTTPException):
        raise error
    logger.warning("http_error", status_code=error.status_code)
    return _response(error.status_code, "HTTP_ERROR", "Ошибка HTTP-запроса")


async def validation_exception_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    fields = sorted({str(item) for issue in error.errors() for item in issue["loc"] if isinstance(item, str)})
    logger.warning("request_validation_failed", fields=fields)
    return _response(422, "VALIDATION_ERROR", "Некорректный запрос", {"fields": fields})


async def unexpected_exception_handler(_request: Request, error: Exception) -> JSONResponse:
    logger.error("unexpected_request_error", error_type=type(error).__name__)
    return _response(500, "INTERNAL_ERROR", "Внутренняя ошибка сервера")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationException, application_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
