"""HTTP-контракты платежей версии v1."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import Currency, PaymentStatus


class CreatePaymentRequest(BaseModel):
    amount: Decimal = Field(max_digits=15, decimal_places=2)
    currency: Currency
    description: str = Field(max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: str = Field(max_length=512)


class CreatePaymentResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime

    @classmethod
    def from_payment(cls, payment: Payment) -> "CreatePaymentResponse":
        return cls(payment_id=payment.id, status=payment.status, created_at=payment.created_at)


class PaymentResponse(BaseModel):
    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None

    @classmethod
    def from_payment(cls, payment: Payment) -> "PaymentResponse":
        return cls(
            payment_id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata=payment.metadata_json,
            status=payment.status,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
        )
