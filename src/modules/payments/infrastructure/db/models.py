from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import DECIMAL, JSON, DateTime, String, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.common.infrastructure.base import BaseModel

# Импортируем типы данных (Value Objects) напрямую из Домена
from src.modules.payments.domain.value_objects import Currency, OutboxEventType, PaymentStatus


class Payment(BaseModel):
    __tablename__ = "payments"

    amount: Mapped[Decimal] = mapped_column(DECIMAL(15, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, native_enum=True, name="currency_enum"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, native_enum=True, name="payment_status_enum"),
        default=PaymentStatus.PENDING,
        index=True,
        nullable=False,
    )
    # Уникальный ключ для защиты от повторных запросов
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    webhook_url: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),)


class OutboxEvent(BaseModel):
    __tablename__ = "outbox_events"

    event_type: Mapped[OutboxEventType] = mapped_column(
        SQLEnum(OutboxEventType, native_enum=True, name="outbox_event_type_enum"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
