"""Общее управление жизненным циклом SQLAlchemy-сессии для UoW модулей."""

from types import TracebackType
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.unit_of_work import AbstractUnitOfWork

_UoW = TypeVar("_UoW", bound="SQLAlchemyBaseUnitOfWork")


class SQLAlchemyBaseUnitOfWork(AbstractUnitOfWork):
    """Создаёт одну сессию на операцию; транзакция фиксируется только явно."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        """Вернуть сессию активного контекста."""
        if self._session is None:
            raise RuntimeError("Unit of Work must be used inside 'async with'")
        return self._session

    async def __aenter__(self: _UoW) -> _UoW:
        if self._session is not None:
            raise RuntimeError("Unit of Work context is already active")
        self._session = self._session_factory()
        await super().__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            try:
                await session.close()
            finally:
                self._session = None

    async def commit(self) -> None:
        """Зафиксировать изменения в активной сессии."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Откатить изменения в активной сессии."""
        await self.session.rollback()
