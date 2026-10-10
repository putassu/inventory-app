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
    litellm_url: str | None = None
    litellm_key: SecretStr = SecretStr("")
    litellm_trusted: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    local_model: str = "gemma3:4b"
    local_image_max_side: int = Field(512, ge=256, le=1024)
    local_image_max_bytes: int = Field(262144, ge=16384, le=1048576)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    embedding_model: str = "bge-m3:latest"
    local_audio_url: str | None = None
    local_audio_model: str | None = None
    local_gatekeeper_model: str | None = None
    local_audio_key: SecretStr = SecretStr("")
    local_audio_trusted: bool = False
    local_audio_verified: bool = False
    cloud_url: str | None = None
    cloud_key: SecretStr = SecretStr("")
    cloud_model: str | None = None
    cloud_proxy: str | None = None
    cloud_api: Literal["openai", "google"] = "openai"
    cloud_json_mode: bool = True
    cloud_reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None
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

    @property
    def cloud_configured(self):
        return bool(
            self.cloud_model
            and (self.litellm_url or self.cloud_url)
            and (self.litellm_key if self.litellm_url else self.cloud_key).get_secret_value()
        )

    @property
    def audio_configured(self):
        return bool(
            self.local_audio_model
            and self.local_audio_verified
            and (
                self.litellm_url and self.litellm_trusted and self.litellm_key.get_secret_value()
                if self.litellm_url
                else self.local_audio_url and self.local_audio_trusted
            )
        )


def model_definitions(config):
    """Одинаковые маршруты при первой установке и обновлении реестра."""
    gateway = bool(config.litellm_url)
    local = "litellm" if gateway else "ollama"
    key = "litellm_key" if gateway else None
    return [
        ("local_vlm", config.local_model, local, "local", key),
        (
            "privacy_asr",
            config.local_gatekeeper_model or config.local_model,
            "litellm" if gateway else "local_audio" if config.local_gatekeeper_model else "ollama",
            "local",
            key or ("local_audio_key" if config.local_gatekeeper_model else None),
        ),
        ("embeddings", config.embedding_model, local, "local", key),
        (
            "local_audio",
            config.local_audio_model or "unconfigured",
            "litellm" if gateway else "local_audio",
            "local",
            key or "local_audio_key",
        ),
        (
            "cloud_primary",
            config.cloud_model or "unconfigured",
            "litellm" if gateway else "cloud",
            "external",
            key or "cloud_key",
        ),
    ]


def local_enabled(config, endpoint):
    if endpoint == "litellm":
        return bool(config.litellm_trusted and config.litellm_key.get_secret_value())
    return endpoint != "local_audio" or config.local_audio_trusted and config.local_audio_verified


@lru_cache
def get_config() -> Config:
    return Config()
