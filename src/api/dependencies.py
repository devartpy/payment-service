"""Внешняя сборка зависимостей HTTP-слоя."""

from collections.abc import Callable
from hmac import compare_digest

import structlog
from fastapi import Header, Request

from src.common.configs import get_fastapi_config
from src.common.exceptions import ApplicationException
from src.modules.payments.application.interfaces import PaymentUnitOfWork
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork

logger = structlog.get_logger(__name__)


async def require_api_key(x_api_key: str | None = Header(alias="X-API-Key", default=None)) -> None:
    logger.debug("api_key_check_started")
    configured = get_fastapi_config().api_key
    if x_api_key is None or not compare_digest(x_api_key, configured):
        logger.warning("api_key_rejected")
        raise ApplicationException("Неверный API-ключ", "UNAUTHORIZED", 401)
    logger.debug("api_key_check_completed")


def get_payment_uow_factory(request: Request) -> Callable[[], PaymentUnitOfWork]:
    session_factory = request.app.state.session_factory
    return lambda: SQLAlchemyPaymentUnitOfWork(session_factory)
