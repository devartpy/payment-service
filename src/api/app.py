"""Сборка HTTP-приложения без настройки логирования процесса."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.main_router import router
from src.common.configs import get_fastapi_config


def create_app() -> FastAPI:
    config = get_fastapi_config()
    app = FastAPI(
        title=config.title,
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

    app.include_router(router)
    return app
