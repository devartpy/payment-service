"""Ошибки нарушения бизнес-правил модуля."""

from decimal import Decimal
from typing import Any


class PaymentDomainException(Exception):
    """Базовая ошибка для контекста платежей."""

    def __init__(self, message: str, code: str, meta: dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.meta = meta or {}
        super().__init__(message)


class InvalidPaymentAmountError(PaymentDomainException):
    """Сумма платежа не прошла валидацию."""

    def __init__(self, provided_amount: Decimal, min_required: Decimal = Decimal("0.0")):
        super().__init__(
            message=f"Сумма платежа {provided_amount} меньше минимально допустимой {min_required}.",
            code="PAYMENT_AMOUNT_TOO_LOW",
            meta={"provided_amount": provided_amount, "min_required": min_required},
        )


class InvalidWebhookURLError(PaymentDomainException):
    """URL вебхука не прошел валидацию."""

    def __init__(self, provided_url: str):
        super().__init__(
            message=f"Некорректный URL вебхука: {provided_url}.",
            code="INVALID_WEBHOOK_URL",
            meta={"provided_url": provided_url},
        )
