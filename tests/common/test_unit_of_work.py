from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.common.infrastructure.sqlalchemy_uow import SQLAlchemyBaseUnitOfWork


def make_uow() -> tuple[SQLAlchemyBaseUnitOfWork, AsyncMock]:
    session = AsyncMock(spec=AsyncSession)
    factory = cast(async_sessionmaker[AsyncSession], Mock(return_value=session))
    return SQLAlchemyBaseUnitOfWork(factory), session


@pytest.mark.asyncio
async def test_commit_is_explicit_and_session_is_closed() -> None:
    uow, session = make_uow()

    async with uow as active:
        assert active.session is session
        await active.commit()

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="async with"):
        await uow.commit()


@pytest.mark.asyncio
async def test_exception_rolls_back_and_closes_session() -> None:
    uow, session = make_uow()

    with pytest.raises(ValueError, match="failure"):
        async with uow:
            raise ValueError("failure")

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
