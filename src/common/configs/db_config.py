from pydantic import Field
from sqlalchemy.engine import URL

from src.common.configs.common import CommonConfig


class DatabaseConfig(CommonConfig):
    """Settings for database connection."""

    host: str = Field(default="localhost", validation_alias="DB_HOST")
    port: int = Field(default=5432, validation_alias="DB_PORT")
    user: str = Field(default="", validation_alias="DB_USER", min_length=1, validate_default=True)
    password: str = Field(default="", validation_alias="DB_PASSWORD", min_length=1, validate_default=True)
    db: str = Field(default="db", validation_alias="DB_NAME")

    @property
    def async_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db,
        )
