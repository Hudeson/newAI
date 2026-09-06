from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["personal", "team", "enterprise"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    profile: Profile = "personal"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/kb.db"
    redis_url: str = ""
    qdrant_url: str = ""

    s3_endpoint: str = ""
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "kb-documents"
    s3_region: str = "us-east-1"

    jwt_secret: str = "dev-change-me-e0"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
