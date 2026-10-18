"""Независимый от инфраструктуры контракт управления транзакцией."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import TypeVar

_UoW = TypeVar("_UoW", bound="AbstractUnitOfWork")


class AbstractUnitOfWork(ABC):
    """Общий контракт для сценариев, использующих ``async with``."""

    async def __aenter__(self: _UoW) -> _UoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None:
        """Зафиксировать транзакцию явно."""

    @abstractmethod
    async def rollback(self) -> None:
        """Откатить текущую транзакцию."""
