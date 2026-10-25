"""Случайная эмуляция платёжного шлюза."""

import asyncio
import random

import structlog

from src.modules.payments.application.interfaces import PaymentGateway
from src.modules.payments.domain.models import Payment
from src.modules.payments.domain.value_objects import PaymentStatus

logger = structlog.get_logger(__name__)


class SimulatedPaymentGateway(PaymentGateway):
    async def process(self, payment: Payment) -> PaymentStatus:
        """Задержка 2–5 секунд и независимый исход 90/10 для каждого вызова."""
        duration = random.uniform(2.0, 5.0)
        logger.debug("gateway_simulation_started", payment_id=str(payment.id), delay_seconds=round(duration, 3))
        await asyncio.sleep(duration)

        if random.random() < 0.10:
            logger.warning("gateway_simulation_failed", payment_id=str(payment.id))
            return PaymentStatus.FAILED

        logger.info("gateway_simulation_succeeded", payment_id=str(payment.id))
        return PaymentStatus.SUCCEEDED
