"""Общие декларативные классы ORM без подключения к базе данных."""

import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Общие метаданные ORM-моделей сервиса."""


class BaseModel(Base):
    """Абстрактная ORM-модель с UUID в качестве первичного ключа."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
