"""Проверки хранения в текущей БД с изоляцией во временной схеме."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from src.common.configs.db_config import DatabaseConfig


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    schema = f"payment_test_{uuid4().hex}"
    url = DatabaseConfig().async_url
    admin_engine = create_async_engine(url, connect_args={"server_settings": {"timezone": "UTC"}})
    test_engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": schema, "timezone": "UTC"}},
    )
    schema_created = False
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            schema_created = True

        async with test_engine.begin() as connection:

            def upgrade_schema(sync_connection: object) -> None:
                config = Config("alembic.ini")
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(upgrade_schema)

        yield async_sessionmaker(bind=test_engine, expire_on_commit=False)
    finally:
        await test_engine.dispose()
        if schema_created:
            async with admin_engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await admin_engine.dispose()
