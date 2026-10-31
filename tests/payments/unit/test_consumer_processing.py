"""Маршрутизация платежа и одной попытки webhook."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from faststream.exceptions import NackMessage, RejectMessage
from pamqp.commands import Basic
from structlog.testing import capture_logs

from src.common.configs.rabbitmq_config import WEBHOOK_READY_QUEUE, WEBHOOK_RETRY_1_QUEUE, WEBHOOK_RETRY_2_QUEUE
from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import Currency, PaymentStatus
from src.modules.payments.infrastructure import consumer as consumer_module
from src.modules.payments.infrastructure import gateway as gateway_module
from src.modules.payments.infrastructure.consumer import handle_failed_payments_dlq, handle_payment, handle_webhook
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
        processed_at=datetime.now(timezone.utc) if status is not PaymentStatus.PENDING else None,
    )


class FakeUow:
    def __init__(self, payment: Payment) -> None:
        self.payments = self
        self.payment = payment
        self.commits = 0
        self.reads = 0

    async def __aenter__(self) -> "FakeUow":
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
    def __init__(self, result: str) -> None:
        self.result = result
        self.calls = 0

    async def notify(self, _payment: Payment) -> str:
        self.calls += 1
        return self.result


class FakeClient:
    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeBroker:
    def __init__(self, confirmation: object = Basic.Ack()) -> None:
        self.confirmation = confirmation
        self.published: list[tuple[dict[str, object], dict[str, object]]] = []

    async def publish(self, payload: dict[str, object], **kwargs: object) -> object:
        self.published.append((payload, kwargs))
        return self.confirmation


def configure_handler(monkeypatch: pytest.MonkeyPatch, uow: FakeUow, gateway: FakeGateway, broker: FakeBroker) -> None:
    monkeypatch.setattr(consumer_module, "session_factory", object())
    monkeypatch.setattr(consumer_module, "SQLAlchemyPaymentUnitOfWork", lambda _factory: uow)
    monkeypatch.setattr(consumer_module, "SimulatedPaymentGateway", lambda: gateway)
    monkeypatch.setattr(consumer_module, "broker", broker)
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
    assert await gateway.process(payment) is PaymentStatus.FAILED
    assert await gateway.process(payment) is PaymentStatus.SUCCEEDED
    assert delays == [3.5, 3.5]


@pytest.mark.asyncio
async def test_duplicate_terminal_message_skips_gateway_and_republishes(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = make_payment()
    uow, gateway, broker = FakeUow(payment), FakeGateway(), FakeBroker()
    configure_handler(monkeypatch, uow, gateway, broker)

    await handle_payment({"payment_id": str(payment.id)})
    await handle_payment({"payment_id": str(payment.id)})

    assert payment.status is PaymentStatus.SUCCEEDED
    assert gateway.calls == 1
    assert uow.commits == 1
    assert uow.reads == 2
    assert [item[0] for item in broker.published] == [
        {"payment_id": str(payment.id), "attempt": 1},
        {"payment_id": str(payment.id), "attempt": 1},
    ]
    assert all(item[1]["routing_key"] == WEBHOOK_READY_QUEUE for item in broker.published)
    assert all(item[1]["mandatory"] and item[1]["persist"] for item in broker.published)


@pytest.mark.asyncio
async def test_handoff_without_confirm_requeues_original(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = make_payment(PaymentStatus.SUCCEEDED)
    uow, gateway, broker = FakeUow(payment), FakeGateway(), FakeBroker(None)
    configure_handler(monkeypatch, uow, gateway, broker)
    with pytest.raises(NackMessage):
        await handle_payment({"payment_id": str(payment.id)})
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_retry_queues_have_ttl_and_return_to_webhook_ready() -> None:
    one, two = consumer_module.RETRY_QUEUES
    assert one.arguments["x-message-ttl"] == 1000
    assert two.arguments["x-message-ttl"] == 2000
    for queue in (one, two):
        assert queue.arguments["x-dead-letter-routing-key"] == WEBHOOK_READY_QUEUE
        assert queue.arguments["x-dead-letter-exchange"] == consumer_module.PAYMENTS_EXCHANGE
        assert queue.durable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "attempt", "routing_key", "rejected"),
    [
        ("success", 1, None, False),
        ("permanent_failure", 1, None, True),
        ("transient_failure", 1, WEBHOOK_RETRY_1_QUEUE, False),
        ("transient_failure", 2, WEBHOOK_RETRY_2_QUEUE, False),
        ("transient_failure", 3, None, True),
    ],
)
async def test_webhook_routes_one_attempt(
    monkeypatch: pytest.MonkeyPatch, result: str, attempt: int, routing_key: str | None, rejected: bool
) -> None:
    payment = make_payment(PaymentStatus.SUCCEEDED)
    uow, gateway, broker = FakeUow(payment), FakeGateway(), FakeBroker()
    notifier = FakeNotifier(result)
    configure_handler(monkeypatch, uow, gateway, broker)
    monkeypatch.setattr(consumer_module, "HTTPWebhookNotifier", lambda _client: notifier)
    payload = {"payment_id": str(payment.id), "attempt": attempt}
    if rejected:
        with pytest.raises(RejectMessage):
            await handle_webhook(payload)
    else:
        await handle_webhook(payload)
    assert notifier.calls == 1
    assert len(broker.published) == int(routing_key is not None)
    if routing_key:
        assert broker.published[0][0] == {"payment_id": str(payment.id), "attempt": attempt + 1}
        assert broker.published[0][1]["routing_key"] == routing_key


@pytest.mark.asyncio
async def test_retry_publish_without_confirm_requeues_same_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    payment = make_payment(PaymentStatus.SUCCEEDED)
    uow, gateway, broker = FakeUow(payment), FakeGateway(), FakeBroker(None)
    configure_handler(monkeypatch, uow, gateway, broker)
    monkeypatch.setattr(consumer_module, "HTTPWebhookNotifier", lambda _client: FakeNotifier("transient_failure"))
    with pytest.raises(NackMessage):
        await handle_webhook({"payment_id": str(payment.id), "attempt": 2})
    assert broker.published[0][0]["attempt"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected",
    [(200, "success"), (400, "permanent_failure"), (302, "permanent_failure"), (503, "transient_failure")],
)
async def test_notifier_makes_one_request_without_sleep(status: int, expected: str) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    payment = make_payment(PaymentStatus.FAILED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with capture_logs() as logs:
            result = await HTTPWebhookNotifier(client).notify(payment)
    assert result == expected
    assert len(seen) == 1
    assert json.loads(seen[0].content)["status"] == "failed"
    assert "private-payment-key" not in str(logs)
    assert payment.webhook_url not in str(logs)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
async def test_network_failure_is_transient(error_type: type[httpx.RequestError]) -> None:
    calls = 0

    def fail(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_type("unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        assert await HTTPWebhookNotifier(client).notify(make_payment(PaymentStatus.SUCCEEDED)) == "transient_failure"
    assert calls == 1


@pytest.mark.asyncio
async def test_invalid_messages_are_rejected() -> None:
    with pytest.raises(RejectMessage):
        await handle_payment({"payment_id": "invalid"})
    for payload in ({"payment_id": "invalid", "attempt": 1}, {"payment_id": str(uuid4()), "attempt": 4}):
        with pytest.raises(RejectMessage):
            await handle_webhook(payload)


@pytest.mark.asyncio
async def test_dead_letter_subscriber_logs_and_acknowledges() -> None:
    payment_id = str(uuid4())
    with capture_logs() as logs:
        await handle_failed_payments_dlq({"payment_id": payment_id})
    assert any(log["event"] == "payment_dead_letter_received" and log["payment_id"] == payment_id for log in logs)
