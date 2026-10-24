"""Неизменяемые объекты значений и перечисления предметной области."""

from enum import Enum


class PaymentStatus(str, Enum):
    NEW = "new"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Currency(str, Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class OutboxEventType(str, Enum):
    PAYMENT_NEW = "payment.new"
