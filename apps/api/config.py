from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    alice_env: str = "beta"
    alice_timezone: str = "America/Santiago"
    alice_host: str = "127.0.0.1"
    alice_port: int = 8000
    alice_metrics_port: int = 9101
    alice_public_origin: str = ""
    alice_executor_name: str = ""  # empty: operating system hostname
    alice_file_root: Path | None = None  # explicit opt-in; no default writable folder

    alice_username: str = "admin"
    alice_password: SecretStr = SecretStr("")
    alice_session_secret: SecretStr = SecretStr("")
    alice_local_only: bool = False

    ollama_base_url: str = "http://127.0.0.1:11434"
    alice_local_provider: Literal["ollama", "lmstudio"] = "ollama"
    lmstudio_base_url: str = "http://127.0.0.1:1234"
    lmstudio_api_token: SecretStr = SecretStr("")
    alice_model_aliases: str = "config/models/aliases.yaml"
    alice_reminders_enabled: bool = False

    alice_cloud_enabled: bool = True
    openrouter_api_key: SecretStr = SecretStr("")
    alice_budget_per_request_usd: float = 0.05
    alice_budget_daily_usd: float = 1.00
    deepseek_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    tavily_api_key: SecretStr = SecretStr("")

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "alice_chunks"
    prometheus_url: str = "http://127.0.0.1:9090"
    alice_grafana_local_url: str = "http://127.0.0.1:3000"

    grafana_external_enabled: bool = False
    grafana_url: str = ""
    grafana_service_account_token: SecretStr = SecretStr("")

    hermes_enabled: bool = False
    hermes_api_url: str = "http://127.0.0.1:8642"
    docker_enabled: bool = False
    docker_allowed_containers: str = "alice-qdrant,alice-prometheus,alice-grafana"
    email_enabled: bool = False
    notebooklm_enabled: bool = False          # C2: sends document content to Google; off unless the user enables it
    notebooklm_cli: str = "notebooklm"

    # Sidecars (loopback only, started by Start-Alice). Integrations degrade to "unavailable" when down.
    memory_enabled: bool = True
    hindsight_url: str = "http://127.0.0.1:8888"
    voice_enabled: bool = True
    tts_url: str = "http://127.0.0.1:8010"
    stt_model: str = "small"
    stt_device: str = "cpu"
    loki_enabled: bool = False

    data_dir: Path = ROOT / "data"
    storage_dir: Path = ROOT / "storage"
    logs_dir: Path = ROOT / "logs"

    max_upload_mb: int = 50
    max_pdf_pages: int = 1000

    @property
    def ops_db(self) -> Path:
        return self.storage_dir / "sqlite" / "alice.db"

    @property
    def tables_db(self) -> Path:
        return self.storage_dir / "sqlite" / "tables.db"


@lru_cache
def settings() -> Settings:
    return Settings()


@lru_cache
def load_yaml(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
