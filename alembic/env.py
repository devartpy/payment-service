import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from src.common.configs import get_db_config
from src.common.infrastructure.base import Base
from src.common.infrastructure.model_registry import load_models

config = context.config

# Настройка логирования из alembic.ini (можно оставить как есть)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_config = get_db_config()

load_models()
target_metadata = Base.metadata

if getattr(config.cmd_opts, "autogenerate", False) and not target_metadata.tables:
    raise RuntimeError("No ORM tables loaded; add models in src/modules/<module>/infrastructure/db/models.py")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=db_config.async_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Создать отдельный движок только на время выполнения миграции."""
    connectable = create_async_engine(
        db_config.async_url,
        connect_args={"server_settings": {"timezone": "UTC"}},
        poolclass=NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
