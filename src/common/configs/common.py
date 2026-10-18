from pydantic_settings import BaseSettings, SettingsConfigDict


# Basic configuration, common to all settings classes
class CommonConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
