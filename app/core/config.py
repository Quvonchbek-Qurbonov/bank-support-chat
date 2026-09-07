from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    api_port: int = 8000

    bank_base_url: str = "https://agrobank.uz"
    bank_menu_url: str = "https://agrobank.uz/api/v1/menu.json"
    bank_api_url: str = "https://agrobank.uz/api/v1/"
    bank_languages: str = "uz,ru,en"
    sync_interval_seconds: int = 900

    database_url: str
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "agrobank_pages"

    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384
    chunk_size: int = 1200
    chunk_overlap: int = 150
    top_k: int = 6
    min_retrieval_score: float = 0.30

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.7-flash"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def languages(self) -> list[str]:
        return [x.strip() for x in self.bank_languages.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
