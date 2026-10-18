from pydantic import Field

from src.common.configs.common import CommonConfig


class FastAPIConfig(CommonConfig):
    """Settings for FastAPI."""

    title: str = Field(default="FastAPI Service", validation_alias="FA_TITLE", min_length=1)
    origins: list[str] = Field(default=[], validation_alias="FA_CORS_ORIGINS")
    enable_docs: bool = Field(default=True, validation_alias="FA_ENABLE_DOCS")
    openapi_url: str = Field(default="/openapi.json", validation_alias="FA_OPENAPI_URL")
    docs_url: str = Field(default="/docs", validation_alias="FA_DOCS_URL")
    redoc_url: str = Field(default="/redoc", validation_alias="FA_REDOC_URL")
