"""Сборка HTTP-приложения и жизненного цикла подключений."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.exception_handlers import register_exception_handlers
from src.api.main_router import router
from src.common.configs import get_fastapi_config
from src.common.infrastructure.database import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine()
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    config = get_fastapi_config()
    app = FastAPI(
        title=config.title,
        lifespan=lifespan,
        openapi_url=config.openapi_url if config.enable_docs else None,
        docs_url=config.docs_url if config.enable_docs else None,
        redoc_url=config.redoc_url if config.enable_docs else None,
    )

    if config.origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    app.include_router(router)
    return app
