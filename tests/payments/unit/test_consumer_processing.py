"""Повторы сообщений, случайный шлюз и ограничение webhook retry."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from faststream.exceptions import NackMessage, RejectMessage
from structlog.testing import capture_logs

from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import Currency, PaymentStatus
from src.modules.payments.infrastructure import consumer as consumer_module
from src.modules.payments.infrastructure import gateway as gateway_module
from src.modules.payments.infrastructure import webhook as webhook_module
from src.modules.payments.infrastructure.consumer import handle_failed_payments_dlq, handle_payment
from src.modules.payments.infrastructure.gateway import SimulatedPaymentGateway
from src.modules.payments.infrastructure.webhook import HTTPWebhookNotifier


def make_payment(status: PaymentStatus = PaymentStatus.PENDING) -> Payment:
    return Payment(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="Test",
        idempotency_key="private-payment-key",
        webhook_url="https://merchant.example/hook",
        status=status,
        processed_at=datetime.now(timezone.utc) if status in (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED) else None,
    )


class FakeUow:
    def __init__(self, payment: Payment) -> None:
        self.payments = self
        self.payment = payment
        self.commits = 0
        self.reads = 0
        self.enters = 0

    async def __aenter__(self) -> "FakeUow":
        self.enters += 1
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get_by_id(self, _payment_id: object) -> Payment:
        self.reads += 1
        return self.payment

    async def update_status(
        self, _payment_id: object, expected: PaymentStatus, new: PaymentStatus, processed_at: datetime
    ) -> bool:
        if self.payment.status is not expected:
            return False
        self.payment.status = new
        self.payment.processed_at = processed_at
        return True

    async def commit(self) -> None:
        self.commits += 1


class FakeGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, _payment: Payment) -> PaymentStatus:
        self.calls += 1
        return PaymentStatus.SUCCEEDED


class FakeNotifier:
    def __init__(self, delivered: bool = True) -> None:
        self.calls = 0
        self.delivered = delivered

    async def notify(self, _payment: Payment) -> bool:
        self.calls += 1
        return self.delivered


class FakeClient:
    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def configure_handler(
    monkeypatch: pytest.MonkeyPatch,
    transaction: FakeUow,
    gateway: FakeGateway,
    notifier: FakeNotifier,
) -> None:
    monkeypatch.setattr(consumer_module, "session_factory", object())
    monkeypatch.setattr(consumer_module, "SQLAlchemyPaymentUnitOfWork", lambda _factory: transaction)
    monkeypatch.setattr(consumer_module, "SimulatedPaymentGateway", lambda: gateway)
    monkeypatch.setattr(consumer_module, "HTTPWebhookNotifier", lambda _client: notifier)
    monkeypatch.setattr(consumer_module, "httpx", SimpleNamespace(AsyncClient=FakeClient))


@pytest.mark.asyncio
async def test_gateway_uses_random_delay_and_90_10_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    draws = iter([0.09, 0.10])

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(gateway_module.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(gateway_module.random, "uniform", lambda _start, _end: 3.5)
    monkeypatch.setattr(gateway_module.random, "random", lambda: next(draws))
    gateway = SimulatedPaymentGateway()
    payment = make_payment()
    first = await gateway.process(payment)
    second = await gateway.process(payment)

    assert first is PaymentStatus.FAILED
    assert second is PaymentStatus.SUCCEEDED
    assert delays == [3.5, 3.5]


@pytest.mark.asyncio
async def test_new_message_is_requeued_without_gateway_or_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = make_payment(PaymentStatus.NEW)
    transaction = FakeUow(payment)
    gateway = FakeGateway()
    notifier = FakeNotifier()
    configure_handler(monkeypatch, transaction, gateway, notifier)
    with pytest.raises(NackMessage):
        await handle_payment({"payment_id": str(payment.id)})

    assert gateway.calls == 0
    assert notifier.calls == 0
    assert transaction.commits == 0


@pytest.mark.asyncio
async def test_duplicate_terminal_message_does_not_call_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = make_payment()
    transaction = FakeUow(payment)
    gateway = FakeGateway()
    notifier = FakeNotifier()
    configure_handler(monkeypatch, transaction, gateway, notifier)

    await handle_payment({"payment_id": str(payment.id)})
    await handle_payment({"payment_id": str(payment.id)})

    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.processed_at is not None and payment.processed_at.utcoffset().total_seconds() == 0
    assert gateway.calls == 1
    assert notifier.calls == 2
    assert transaction.commits == 1
    assert transaction.reads == 2
    assert transaction.enters == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statuses", "expected", "delays"),
    [
        ([200], True, []),
        ([400], False, []),
        ([500, 502, 503], False, [1.0, 2.0]),
        ([500, 200], True, [1.0]),
        ([302], False, []),
    ],
)
async def test_webhook_response_policy(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    expected: bool,
    delays: list[float],
) -> None:
    seen: list[httpx.Request] = []
    actual_delays: list[float] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(statuses[len(seen) - 1])

    async def record_sleep(delay: float) -> None:
        actual_delays.append(delay)

    monkeypatch.setattr(webhook_module.asyncio, "sleep", record_sleep)
    payment = make_payment(PaymentStatus.FAILED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with capture_logs() as logs:
            result = await HTTPWebhookNotifier(client).notify(payment)

    assert result is expected
    assert len(seen) == len(statuses)
    assert actual_delays == delays
    assert seen[0].method == "POST"
    assert json.loads(seen[0].content)["status"] == "failed"
    assert "private-payment-key" not in str(logs)
    assert payment.webhook_url not in str(logs)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
async def test_network_error_retries_three_times(
    monkeypatch: pytest.MonkeyPatch, error_type: type[httpx.RequestError]
) -> None:
    calls = 0
    delays: list[float] = []

    def fail(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_type("unavailable", request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(webhook_module.asyncio, "sleep", record_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        result = await HTTPWebhookNotifier(client).notify(make_payment(PaymentStatus.SUCCEEDED))

    assert result is False
    assert calls == 3
    assert delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_invalid_payment_id_is_rejected() -> None:
    with pytest.raises(RejectMessage):
        await handle_payment({"payment_id": "invalid"})


@pytest.mark.asyncio
async def test_dead_letter_subscriber_logs_and_acknowledges() -> None:
    payment_id = str(uuid4())

    with capture_logs() as logs:
        await handle_failed_payments_dlq({"payment_id": payment_id})

    assert any(
        log["event"] == "payment_dead_letter_received"
        and log["log_level"] == "critical"
        and log["payment_id"] == payment_id
        for log in logs
    )
