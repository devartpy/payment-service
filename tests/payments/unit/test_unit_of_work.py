"""Проверки жизненного цикла платежного Unit of Work без БД."""

from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.domain.value_objects import Currency, OutboxEventType
from src.modules.payments.infrastructure import repositories as repositories_module
from src.modules.payments.infrastructure import unit_of_work as uow_module
from src.modules.payments.infrastructure.db import mappers as mappers_module
from src.modules.payments.infrastructure.unit_of_work import SQLAlchemyPaymentUnitOfWork


def make_uow() -> tuple[SQLAlchemyPaymentUnitOfWork, AsyncMock]:
    session = AsyncMock(spec=AsyncSession)
    factory = cast(async_sessionmaker[AsyncSession], Mock(return_value=session))
    return SQLAlchemyPaymentUnitOfWork(factory), session


@pytest.mark.asyncio
async def test_repositories_share_one_session_and_commit_is_explicit() -> None:
    uow, session = make_uow()

    async with uow as transaction:
        assert transaction.payments._session is session
        assert transaction.outbox._session is session
        session.commit.assert_not_awaited()
        await transaction.commit()

    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="async with"):
        _ = uow.payments
    with pytest.raises(RuntimeError, match="async with"):
        _ = uow.outbox


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_and_closes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = Mock()
    monkeypatch.setattr(uow_module, "logger", logger)
    uow, session = make_uow()
    session.commit.side_effect = RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        async with uow as transaction:
            await transaction.commit()

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
    logger.error.assert_called_once_with("payment_uow_commit_failed", error_type="RuntimeError")


@pytest.mark.asyncio
async def test_clean_exit_without_commit_discards_work() -> None:
    uow, session = make_uow()

    async with uow:
        pass

    session.commit.assert_not_awaited()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_nested_entry_does_not_close_outer_transaction() -> None:
    uow, session = make_uow()

    async with uow as transaction:
        with pytest.raises(RuntimeError, match="already active"):
            async with uow:
                pass
        assert transaction.payments._session is session
        await transaction.commit()

    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_transaction_logs_omit_sensitive_payment_data(monkeypatch: pytest.MonkeyPatch) -> None:
    uow_logger = Mock()
    repository_logger = Mock()
    mapper_logger = Mock()
    monkeypatch.setattr(uow_module, "logger", uow_logger)
    monkeypatch.setattr(repositories_module, "logger", repository_logger)
    monkeypatch.setattr(mappers_module, "logger", mapper_logger)
    payment = Payment(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="test",
        idempotency_key="private-idempotency-key",
        webhook_url="https://merchant.example/private-webhook",
    )
    event = OutboxEvent(event_type=OutboxEventType.PAYMENT_NEW, payload={"secret": "private-payload"})
    uow, _ = make_uow()

    async with uow as transaction:
        await transaction.payments.add(payment)
        await transaction.outbox.add(event)
        await transaction.commit()

    uow_logger.info.assert_called_once_with("payment_uow_commit_completed")
    log_calls = repr(uow_logger.mock_calls + repository_logger.mock_calls + mapper_logger.mock_calls)
    assert "private-idempotency-key" not in log_calls
    assert "private-webhook" not in log_calls
    assert "private-payload" not in log_calls
