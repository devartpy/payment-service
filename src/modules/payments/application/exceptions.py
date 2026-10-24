"""Ошибки сценариев платежей."""

from src.common.exceptions import ApplicationException


class PaymentNotFoundError(ApplicationException):
    def __init__(self) -> None:
        super().__init__("Платёж не найден", "PAYMENT_NOT_FOUND", 404)


class IdempotencyConflictError(ApplicationException):
    def __init__(self) -> None:
        super().__init__("Ключ идемпотентности уже использован", "IDEMPOTENCY_CONFLICT", 409)
