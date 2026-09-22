"""Параметры развёртывания; пользовательские настройки хранятся в БД."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INV_", env_file=(".env", ".env.local"), extra="ignore")

    database_url: str = "postgresql+asyncpg://inventory:inventory@127.0.0.1:55432/inventory"
    redis_url: str = "redis://127.0.0.1:56379/0"
    jwt_secret: SecretStr = SecretStr("")
    jwt_issuer: str = "inventarizator"
    jwt_audience: str = "inventory-client"
    access_minutes: int = 15
    refresh_days: int = 30
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    cookie_secure: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    local_model: str = "gemma3:4b"
    local_image_max_side: int = Field(512, ge=256, le=1024)
    local_image_max_bytes: int = Field(262144, ge=16384, le=1048576)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    embedding_model: str = "bge-m3:latest"
    local_audio_url: str | None = None
    local_audio_model: str | None = None
    local_audio_key: SecretStr = SecretStr("")
    local_audio_trusted: bool = False
    local_audio_verified: bool = False
    cloud_url: str | None = None
    cloud_key: SecretStr = SecretStr("")
    cloud_model: str | None = None
    cloud_proxy: str | None = None
    storage_backend: str = "s3"
    media_root: Path = Path("data/media-v1")
    s3_endpoint: str = "http://127.0.0.1:59000"
    s3_access_key: str = "inventory"
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "inventory-private"
    qdrant_url: str = "http://127.0.0.1:56333"
    search_collection: str = "inventory_bge_m3_bm25_v1"
    prompt_dir: Path = Path(__file__).resolve().parents[1] / "prompts"
    backup_root: Path = Path("data/backups")


@lru_cache
def get_config() -> Config:
    return Config()
