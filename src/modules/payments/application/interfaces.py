"""Контракты хранения платежей и транзакции для сценариев приложения."""

import uuid
from abc import abstractmethod
from datetime import datetime
from typing import Protocol

from src.common.unit_of_work import AbstractUnitOfWork
from src.modules.payments.domain.models import OutboxEvent, Payment
from src.modules.payments.domain.value_objects import PaymentStatus


class PaymentRepository(Protocol):
    """Операции с платежами внутри активного Unit of Work."""

    async def add(self, payment: Payment) -> None:
        """Подготовить новый платёж к записи без фиксации транзакции."""

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        """Вернуть платёж или ``None``, если ID не найден."""

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        """Вернуть ранее созданный платёж или ``None``."""

    async def update_status(
        self,
        payment_id: uuid.UUID,
        expected_status: PaymentStatus,
        new_status: PaymentStatus,
        processed_at: datetime | None = None,
    ) -> bool:
        """Условно изменить статус; ``False`` означает отсутствие записи или иной текущий статус."""


class OutboxRepository(Protocol):
    """Операции с исходящими событиями внутри активного Unit of Work."""

    async def add(self, event: OutboxEvent) -> None:
        """Подготовить новое событие к записи без фиксации транзакции."""

    async def get_by_id(self, event_id: uuid.UUID) -> OutboxEvent | None:
        """Вернуть событие или ``None``, если ID не найден."""

    async def delete(self, event_id: uuid.UUID) -> bool:
        """Удалить событие; ``False`` означает отсутствие записи."""


class PaymentUnitOfWork(AbstractUnitOfWork):
    """Одна транзакция для платежа и outbox; используется через ``async with``."""

    @property
    @abstractmethod
    def payments(self) -> PaymentRepository:
        """Репозиторий платежей активной транзакции."""

    @property
    @abstractmethod
    def outbox(self) -> OutboxRepository:
        """Репозиторий событий той же транзакции."""
