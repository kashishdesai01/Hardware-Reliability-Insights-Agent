from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hria:hria@localhost:5432/hria"
    redis_url: str = "redis://localhost:6379/0"
    planner_provider: str = "rules"
    openai_api_key: str | None = None
    openai_model: str = "gpt-6-astra"
    log_level: str = "INFO"
    dataset_version: str = "seed-4471-v1"
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    )
    maximum_query_rows: int = Field(default=200, ge=1, le=1_000)

    @property
    def allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
