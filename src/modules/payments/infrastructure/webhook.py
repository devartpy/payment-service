"""Одна HTTP-попытка доставки webhook."""

from typing import Literal

import httpx
import structlog

from src.modules.payments.application.interfaces import WebhookNotifier
from src.modules.payments.domain.models import Payment

logger = structlog.get_logger(__name__)
WebhookResult = Literal["success", "transient_failure", "permanent_failure"]


class HTTPWebhookNotifier(WebhookNotifier):
    def __init__(self, client: httpx.AsyncClient, *, timeout_seconds: float = 5.0) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def notify(self, payment: Payment) -> WebhookResult:
        logger.debug("webhook_attempt_started", payment_id=str(payment.id))
        payload = {
            "payment_id": str(payment.id),
            "idempotency_key": payment.idempotency_key,
            "status": payment.status.value,
            "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
        }
        try:
            response = await self._client.post(payment.webhook_url, json=payload, timeout=self._timeout_seconds)
        except httpx.RequestError as error:
            logger.warning(
                "webhook_attempt_transient_failure", payment_id=str(payment.id), error_type=type(error).__name__
            )
            return "transient_failure"
        if response.status_code == 200:
            logger.info("webhook_delivery_succeeded", payment_id=str(payment.id))
            return "success"
        if 500 <= response.status_code <= 599:
            logger.warning(
                "webhook_attempt_transient_failure", payment_id=str(payment.id), status_code=response.status_code
            )
            return "transient_failure"
        logger.warning("webhook_delivery_rejected", payment_id=str(payment.id), status_code=response.status_code)
        return "permanent_failure"
