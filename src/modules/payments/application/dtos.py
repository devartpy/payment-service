"""Независимые от HTTP данные сценариев платежей."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.modules.payments.domain.value_objects import Currency


@dataclass(frozen=True)
class CreatePaymentCommand:
    amount: Decimal
    currency: Currency
    description: str
    webhook_url: str
    idempotency_key: str
    metadata_json: dict[str, Any] = field(default_factory=dict)
