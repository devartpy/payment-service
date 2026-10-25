"""HTTP webhook с retry только для временных ошибок доставки."""

import asyncio

import httpx
import structlog

from src.modules.payments.application.interfaces import WebhookNotifier
from src.modules.payments.domain.models import Payment

logger = structlog.get_logger(__name__)


class HTTPWebhookNotifier(WebhookNotifier):
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._timeout_seconds = timeout_seconds

    async def notify(self, payment: Payment) -> bool:
        logger.debug("webhook_delivery_started", payment_id=str(payment.id))
        payload = {
            "payment_id": str(payment.id),
            "idempotency_key": payment.idempotency_key,
            "status": payment.status.value,
            "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
        }
        for attempt in range(1, self._max_attempts + 1):
            logger.debug("webhook_attempt_started", payment_id=str(payment.id), attempt=attempt)
            try:
                response = await self._client.post(
                    payment.webhook_url,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except httpx.RequestError as error:
                logger.warning(
                    "webhook_attempt_transient_failure",
                    payment_id=str(payment.id),
                    attempt=attempt,
                    error_type=type(error).__name__,
                )
            else:
                if response.status_code == 200:
                    logger.info("webhook_delivery_succeeded", payment_id=str(payment.id), attempt=attempt)
                    return True
                if not 500 <= response.status_code <= 599:
                    logger.warning(
                        "webhook_delivery_rejected",
                        payment_id=str(payment.id),
                        attempt=attempt,
                        status_code=response.status_code,
                    )
                    return False
                logger.warning(
                    "webhook_attempt_transient_failure",
                    payment_id=str(payment.id),
                    attempt=attempt,
                    status_code=response.status_code,
                )

            if attempt < self._max_attempts:
                delay = self._base_delay_seconds * 2 ** (attempt - 1)
                logger.debug("webhook_retry_scheduled", payment_id=str(payment.id), delay_seconds=delay)
                await asyncio.sleep(delay)

        logger.warning("webhook_delivery_exhausted", payment_id=str(payment.id), attempts=self._max_attempts)
        return False
