"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM
    anthropic_api_key: str
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_model_thinking: str = "claude-3-7-sonnet-20250219"

    # Embeddings
    voyage_api_key: str
    voyage_model: str = "voyage-3"

    # Vector store
    pinecone_api_key: str
    pinecone_index_name: str = "peritus"
    pinecone_environment: str = "us-east-1"

    # Sources
    exa_api_key: str
    firecrawl_api_key: str = ""

    # Storage
    storage_base_path: str = "./storage/peritus"

    # API
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    host: str = "0.0.0.0"
    port: int = 8000

    # Graph extraction
    max_paths_per_chunk: int = 15
    max_source_docs: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
