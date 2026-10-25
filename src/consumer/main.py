"""Локальный запуск consumer: `python -m src.consumer.main`."""

import asyncio

from src.consumer.app import app

if __name__ == "__main__":
    asyncio.run(app.run())
