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

    jwt_secret: str = "dev-change-me-e0-please-use-32bytes-min"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    local_storage_dir: str = "./data/objects"
    # Comma-separated extra CORS origins for remote/local deploy, e.g.
    # http://192.168.1.10:3000,http://kb.example.com
    cors_origins: str = ""
    cors_origin_regex: str = r"https://.*\.trycloudflare\.com"

    # Real LLM gateway (OpenAI-compatible + Ollama)
    llm_provider: str = "local"  # local | openai_compatible | ollama
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    llm_timeout_seconds: float = 60.0
    credentials_secret: str = ""

    # Knowledge graph (M5)
    graph_extract_on_ingest: bool = False
    graph_extract_max_chunks_per_doc: int = 40
    graph_extract_max_docs_per_day: int = 20
    graph_neighbor_max_depth: int = 2
    graph_ask_augment_default: bool = False
    graph_local_fallback: bool = True

    # Education KB (K12 pilot)
    edu_enabled: bool = True
    edu_require_license: bool = True
    edu_default_stage: str = "junior"
    edu_similar_top_k: int = 5
    edu_official_fetch_enabled: bool = True
    edu_official_mode: str = "fixture"  # fixture | live
    edu_official_allow_hosts: str = ""
    edu_official_timeout_seconds: float = 30.0

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url

    @property
    def cors_origin_list(self) -> list[str]:
        base = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
        extra = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return base + extra


@lru_cache
def get_settings() -> Settings:
    return Settings()
