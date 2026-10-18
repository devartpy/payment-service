"""Фабрики движка и сессий для процессов, работающих с PostgreSQL."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.common.configs import get_db_config


def create_engine() -> AsyncEngine:
    """Создать движок при инициализации процесса, использующего БД."""
    return create_async_engine(get_db_config().async_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создать фабрику независимых асинхронных сессий."""
    return async_sessionmaker(bind=engine, expire_on_commit=False)
