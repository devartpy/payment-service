"""Порядок публикации и фиксации outbox без внешних сервисов."""

from collections.abc import Callable
from typing import cast
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker
from pamqp.commands import Basic
from structlog.testing import capture_logs

from src.modules.payments.application.interfaces import PaymentUnitOfWork
from src.modules.payments.application.use_cases import RelayOutbox
from src.modules.payments.domain.models import OutboxEvent
from src.modules.payments.domain.value_objects import OutboxEventType
from src.modules.payments.infrastructure.publisher import PUBLISH_TIMEOUT_SECONDS, RabbitOutboxPublisher


def make_event() -> OutboxEvent:
    return OutboxEvent(OutboxEventType.PAYMENT_NEW, {"payment_id": str(uuid4())})


class FakeOutbox:
    def __init__(self, events: list[OutboxEvent], actions: list[str]) -> None:
        self.events = events
        self.actions = actions
        self.staged: list[OutboxEvent] = []

    async def list_pending(self) -> list[OutboxEvent]:
        self.actions.append("list")
        return list(self.events)

    async def delete(self, event_id: object) -> bool:
        self.actions.append(f"delete:{event_id}")
        match = next((event for event in self.events if event.id == event_id), None)
        if match is None:
            return False
        self.staged.append(match)
        return True


class FakeUoW:
    def __init__(self, outbox: FakeOutbox, actions: list[str], fail_commit: Callable[[], bool]) -> None:
        self.outbox = outbox
        self.actions = actions
        self.fail_commit = fail_commit

    async def __aenter__(self) -> "FakeUoW":
        self.actions.append("enter")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.outbox.staged.clear()
        self.actions.append("exit")

    async def commit(self) -> None:
        self.actions.append("commit")
        if self.fail_commit():
            raise RuntimeError("database unavailable")
        for event in self.outbox.staged:
            self.outbox.events.remove(event)
        self.outbox.staged.clear()

    async def rollback(self) -> None:
        self.actions.append("rollback")
        self.outbox.staged.clear()


class FakePublisher:
    def __init__(self, actions: list[str], fail_event: OutboxEvent | None = None) -> None:
        self.actions = actions
        self.fail_event = fail_event

    async def publish(self, event: OutboxEvent) -> None:
        self.actions.append(f"publish:{event.id}")
        if event is self.fail_event:
            raise RuntimeError("not confirmed")


@pytest.mark.asyncio
async def test_relay_reads_empty_outbox() -> None:
    actions: list[str] = []
    outbox = FakeOutbox([], actions)
    relay = RelayOutbox(
        cast(Callable[[], PaymentUnitOfWork], lambda: FakeUoW(outbox, actions, lambda: False)), FakePublisher(actions)
    )

    assert await relay.execute() == 0
    assert actions == ["enter", "list", "exit"]


@pytest.mark.asyncio
async def test_relay_confirms_then_deletes_and_commits_each_event() -> None:
    actions: list[str] = []
    first, second = make_event(), make_event()
    outbox = FakeOutbox([first, second], actions)
    relay = RelayOutbox(
        cast(Callable[[], PaymentUnitOfWork], lambda: FakeUoW(outbox, actions, lambda: False)), FakePublisher(actions)
    )

    assert await relay.execute() == 2
    assert actions == [
        "enter",
        "list",
        f"publish:{first.id}",
        f"delete:{first.id}",
        "commit",
        f"publish:{second.id}",
        f"delete:{second.id}",
        "commit",
        "exit",
    ]
    assert outbox.events == []


@pytest.mark.asyncio
async def test_relay_keeps_failed_event_and_processes_next() -> None:
    actions: list[str] = []
    first, second = make_event(), make_event()
    outbox = FakeOutbox([first, second], actions)
    relay = RelayOutbox(
        cast(Callable[[], PaymentUnitOfWork], lambda: FakeUoW(outbox, actions, lambda: False)),
        FakePublisher(actions, first),
    )

    with capture_logs() as logs:
        assert await relay.execute() == 1
    assert outbox.events == [first]
    assert f"delete:{first.id}" not in actions
    assert "rollback" in actions
    assert any(log["event"] == "outbox_relay_event_failed" for log in logs)
    assert str(first.payload["payment_id"]) not in str(logs)


@pytest.mark.asyncio
async def test_relay_retries_after_failed_commit() -> None:
    actions: list[str] = []
    event = make_event()
    outbox = FakeOutbox([event], actions)
    fail = True

    def fail_once() -> bool:
        nonlocal fail
        if fail:
            fail = False
            return True
        return False

    relay = RelayOutbox(
        cast(Callable[[], PaymentUnitOfWork], lambda: FakeUoW(outbox, actions, fail_once)), FakePublisher(actions)
    )
    assert await relay.execute() == 0
    assert outbox.events == [event]
    assert await relay.execute() == 1
    assert actions.count(f"publish:{event.id}") == 2
    assert outbox.events == []


@pytest.mark.asyncio
async def test_relay_rolls_back_failed_commit_and_uses_same_uow_for_next_event() -> None:
    actions: list[str] = []
    first, second = make_event(), make_event()
    outbox = FakeOutbox([first, second], actions)
    fail = True

    def fail_once() -> bool:
        nonlocal fail
        if fail:
            fail = False
            return True
        return False

    relay = RelayOutbox(
        cast(Callable[[], PaymentUnitOfWork], lambda: FakeUoW(outbox, actions, fail_once)), FakePublisher(actions)
    )
    assert await relay.execute() == 1
    assert outbox.events == [first]
    assert actions == [
        "enter",
        "list",
        f"publish:{first.id}",
        f"delete:{first.id}",
        "commit",
        "rollback",
        f"publish:{second.id}",
        f"delete:{second.id}",
        "commit",
        "exit",
    ]


class BrokerStub:
    def __init__(self, confirmation: object) -> None:
        self.confirmation = confirmation
        self.kwargs: dict[str, object] = {}

    async def publish(self, _payload: object, **kwargs: object) -> object:
        self.kwargs = kwargs
        return self.confirmation


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", [None, Basic.Nack(), Basic.Reject()])
async def test_rabbit_adapter_rejects_missing_or_negative_confirmation(confirmation: object) -> None:
    stub = BrokerStub(confirmation)
    publisher = RabbitOutboxPublisher(cast(RabbitBroker, stub))
    with pytest.raises(RuntimeError, match="did not confirm"):
        await publisher.publish(make_event())


@pytest.mark.asyncio
async def test_rabbit_adapter_requests_persistent_mandatory_delivery() -> None:
    stub = BrokerStub(Basic.Ack())
    event = make_event()
    publisher = RabbitOutboxPublisher(cast(RabbitBroker, stub))
    await publisher.publish(event)
    assert stub.kwargs["mandatory"] is True
    assert stub.kwargs["persist"] is True
    assert stub.kwargs["timeout"] == PUBLISH_TIMEOUT_SECONDS
    assert stub.kwargs["message_id"] == str(event.id)
