from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: SecretStr = Field(min_length=1)
    database_url: str
    rabbitmq_url: str
    webhook_timeout: float = Field(default=10, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
