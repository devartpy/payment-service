"""Доменные сущности и агрегаты модуля без зависимостей от фреймворков."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from src.modules.payments.domain.exceptions import InvalidPaymentAmountError, InvalidWebhookURLError
from src.modules.payments.domain.value_objects import Currency, OutboxEventType, PaymentStatus


class Payment:
    """доменная сущность Платежа."""

    def __init__(
        self,
        amount: Decimal,
        currency: Currency,
        description: str,
        idempotency_key: str,
        webhook_url: str,
        metadata_json: dict[str, Any] | None = None,
        id: uuid.UUID | None = None,
        status: PaymentStatus = PaymentStatus.NEW,
        created_at: datetime | None = None,
        processed_at: datetime | None = None,
    ):
        if amount <= 0:
            raise InvalidPaymentAmountError(provided_amount=amount, min_required=Decimal("0.0"))

        try:
            parsed_url = urlparse(webhook_url)
            if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
                raise InvalidWebhookURLError(provided_url=webhook_url)
        except Exception as err:
            raise InvalidWebhookURLError(provided_url=webhook_url) from err

        self.id = id or uuid.uuid4()
        self.amount = amount
        self.currency = currency
        self.description = description
        self.metadata_json = metadata_json or {}
        self.status = status
        self.idempotency_key = idempotency_key
        self.webhook_url = webhook_url
        self.created_at = created_at or datetime.now(timezone.utc)
        self.processed_at = processed_at

    def new_event_payload(self) -> dict[str, str]:
        """Данные события о создании платежа."""
        return {"payment_id": str(self.id)}


class OutboxEvent:
    """доменная сущность События Outbox."""

    def __init__(
        self,
        event_type: OutboxEventType,
        payload: dict[str, Any],
        id: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.event_type = event_type
        self.payload = payload
        self.created_at = created_at or datetime.now(timezone.utc)
