"""Проверки повторного ключа и сбоя хранения в сценарии."""

from collections.abc import Callable
from decimal import Decimal
from typing import cast

import pytest
from structlog.testing import capture_logs

from src.modules.payments.application.dtos import CreatePaymentCommand
from src.modules.payments.application.interfaces import PaymentUnitOfWork
from src.modules.payments.application.use_cases import CreatePayment
from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import Currency


class FakePayments:
    def __init__(self, existing: Payment | None) -> None:
        self.existing = existing
        self.added: list[Payment] = []

    async def get_by_idempotency_key(self, _key: str) -> Payment | None:
        return self.existing

    async def add(self, payment: Payment) -> None:
        self.added.append(payment)


class FakeOutbox:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def add(self, event: object) -> None:
        self.added.append(event)


class FakeUow:
    def __init__(self, existing: Payment | None, commit_error: Exception | None = None) -> None:
        self.payments = FakePayments(existing)
        self.outbox = FakeOutbox()
        self.commit_error = commit_error
        self.commits = 0
        self.rolled_back = False

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, error_type: type[BaseException] | None, *_args: object) -> None:
        self.rolled_back = error_type is not None

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error


def command() -> CreatePaymentCommand:
    return CreatePaymentCommand(
        amount=Decimal("12.50"),
        currency=Currency.RUB,
        description="Payment",
        metadata_json={"order": 1},
        webhook_url="https://merchant.example/hook",
        idempotency_key="private-key-value",
    )


@pytest.mark.asyncio
async def test_existing_key_returns_payment_without_new_write() -> None:
    request = command()
    existing = Payment(
        amount=request.amount,
        currency=request.currency,
        description=request.description,
        metadata_json=request.metadata_json,
        webhook_url=request.webhook_url,
        idempotency_key=request.idempotency_key,
    )
    transaction = FakeUow(existing)
    factory = cast(Callable[[], PaymentUnitOfWork], lambda: transaction)

    with capture_logs() as logs:
        result = await CreatePayment(factory).execute(request)

    assert result is existing
    assert transaction.commits == 0
    assert transaction.payments.added == []
    assert transaction.outbox.added == []
    assert "private-key-value" not in str(logs)
    assert "https://merchant.example/hook" not in str(logs)


@pytest.mark.asyncio
async def test_storage_failure_is_propagated() -> None:
    first = FakeUow(None, RuntimeError("storage unavailable"))
    factory = cast(Callable[[], PaymentUnitOfWork], lambda: first)

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await CreatePayment(factory).execute(command())

    assert first.rolled_back
