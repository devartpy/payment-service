"""Одна SQLAlchemy-транзакция для платежей и событий outbox."""

from types import TracebackType

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.infrastructure.sqlalchemy_uow import SQLAlchemyBaseUnitOfWork
from src.modules.payments.application.interfaces import OutboxRepository, PaymentRepository, PaymentUnitOfWork
from src.modules.payments.infrastructure.repositories import SQLAlchemyOutboxRepository, SQLAlchemyPaymentRepository

logger = structlog.get_logger(__name__)


class SQLAlchemyPaymentUnitOfWork(SQLAlchemyBaseUnitOfWork, PaymentUnitOfWork):
    """Связывает оба репозитория с одной сессией активного контекста."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(session_factory)
        self._payments: SQLAlchemyPaymentRepository | None = None
        self._outbox: SQLAlchemyOutboxRepository | None = None

    @property
    def payments(self) -> PaymentRepository:
        if self._payments is None:
            raise RuntimeError("Unit of Work must be used inside 'async with'")
        return self._payments

    @property
    def outbox(self) -> OutboxRepository:
        if self._outbox is None:
            raise RuntimeError("Unit of Work must be used inside 'async with'")
        return self._outbox

    async def __aenter__(self) -> "SQLAlchemyPaymentUnitOfWork":
        logger.debug("payment_uow_enter_started")
        try:
            await super().__aenter__()
        except Exception as error:
            logger.error("payment_uow_enter_failed", error_type=type(error).__name__)
            raise
        try:
            self._payments = SQLAlchemyPaymentRepository(self.session)
            self._outbox = SQLAlchemyOutboxRepository(self.session)
        except Exception as error:
            logger.error("payment_uow_enter_failed", error_type=type(error).__name__)
            try:
                await super().__aexit__(type(error), error, error.__traceback__)
            finally:
                self._payments = None
                self._outbox = None
            raise
        logger.debug("payment_uow_enter_completed")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        logger.debug("payment_uow_exit_started", has_error=exc_type is not None)
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        except Exception as error:
            logger.error("payment_uow_exit_failed", error_type=type(error).__name__)
            raise
        finally:
            self._payments = None
            self._outbox = None
        logger.debug("payment_uow_exit_completed")

    async def commit(self) -> None:
        logger.debug("payment_uow_commit_started")
        try:
            await super().commit()
        except Exception as error:
            logger.error("payment_uow_commit_failed", error_type=type(error).__name__)
            raise
        logger.info("payment_uow_commit_completed")

    async def rollback(self) -> None:
        logger.debug("payment_uow_rollback_started")
        try:
            await super().rollback()
        except Exception as error:
            logger.error("payment_uow_rollback_failed", error_type=type(error).__name__)
            raise
        logger.warning("payment_uow_rollback_completed")
