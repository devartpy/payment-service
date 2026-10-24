"""Маршруты создания и чтения платежей."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header

from src.api.dependencies import get_payment_uow_factory, require_api_key
from src.common.exceptions import ApplicationException
from src.modules.payments.api.v1.schemas import CreatePaymentRequest, CreatePaymentResponse, PaymentResponse
from src.modules.payments.application.dtos import CreatePaymentCommand
from src.modules.payments.application.interfaces import PaymentUnitOfWork
from src.modules.payments.application.use_cases import CreatePayment, GetPayment

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"], dependencies=[Depends(require_api_key)])


@router.post("", status_code=202, response_model=CreatePaymentResponse)
async def create_payment(
    body: CreatePaymentRequest,
    uow_factory: Annotated[Callable[[], PaymentUnitOfWork], Depends(get_payment_uow_factory)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreatePaymentResponse:
    logger.debug("payment_post_started")
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 255:
        raise ApplicationException("Требуется корректный Idempotency-Key", "INVALID_IDEMPOTENCY_KEY")

    command = CreatePaymentCommand(
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        metadata_json=body.metadata,
        webhook_url=body.webhook_url,
        idempotency_key=idempotency_key,
    )
    payment = await CreatePayment(uow_factory).execute(command)
    logger.info("payment_post_completed", payment_id=str(payment.id))
    return CreatePaymentResponse.from_payment(payment)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    uow_factory: Annotated[Callable[[], PaymentUnitOfWork], Depends(get_payment_uow_factory)],
) -> PaymentResponse:
    logger.debug("payment_get_http_started", payment_id=str(payment_id))
    payment = await GetPayment(uow_factory).execute(payment_id)
    logger.info("payment_get_http_completed", payment_id=str(payment_id))
    return PaymentResponse.from_payment(payment)
