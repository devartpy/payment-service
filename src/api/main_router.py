"""Общий маршрутизатор API; подключайте сюда маршруты бизнес-модулей."""

from fastapi import APIRouter

from src.modules.payments.api.v1.router import router as payments_router

router = APIRouter()
router.include_router(payments_router)
