"""Configuração via ambiente + YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///data/monitor.db"
    api_trigger_token: str = "change-me"
    schedule_cron: str = "0 7 * * 1-5"
    schedule_hour: int = 7
    tz: str = "America/Sao_Paulo"
    job_max_attempts: int = 3

    djen_enable: bool = True
    djen_base_url: str = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
    djen_max_concurrency: int = 2
    djen_overlap_hours: int = 48

    datajud_enable: bool = True
    datajud_mode: Literal["selective", "confirm_and_fallback", "fallback_only", "off"] = (
        "selective"
    )
    datajud_api_key: str = ""
    datajud_api_key_url: str = "https://datajud-wiki.cnj.jus.br/api-publica/acesso/"
    datajud_max_concurrency: int = 3
    datajud_base_url: str = "https://api-publica.datajud.cnj.jus.br"

    cna_enabled: bool = False
    cna_api_token: str = ""

    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4"
    openrouter_fallback_models: str = "anthropic/claude-sonnet-4.6,openai/gpt-5.2-mini"
    openrouter_max_concurrency: int = 2
    openrouter_timeout_seconds: int = 40
    openrouter_max_retries: int = 2
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    resend_api_key: str = ""
    resend_max_concurrency: int = 1
    email_from: str = ""
    email_to: str = ""

    monitoramentos_path: str = "config/monitoramentos.yaml"
    config_dir: str = "config"
    outbox_dir: str = "data/outbox"

    ui_session_secret: str = "change-me-ui-session-secret"
    ui_admin_user: str = "admin"
    ui_admin_password: str = ""
    ui_session_hours: int = 72

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def openrouter_fallback_list(self) -> list[str]:
        return [m.strip() for m in self.openrouter_fallback_models.split(",") if m.strip()]

    def config_path(self, name: str) -> Path:
        return Path(self.config_dir) / name


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_monitoramentos(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    path = Path(s.monitoramentos_path)
    if not path.exists():
        example = Path("config/monitoramentos.example.yaml")
        if example.exists():
            return load_yaml(example)
        return {"monitoramentos": {}}
    return load_yaml(path)


def load_cobertura(settings: Settings | None = None) -> dict[str, Any]:
    cfg = load_monitoramentos(settings)
    cobertura = dict(cfg.get("cobertura") or {})
    # merge tribunais_destaque.yaml
    s = settings or get_settings()
    extra = load_yaml(s.config_path("tribunais_destaque.yaml"))
    if not cobertura.get("tribunais_destaque") and extra.get("tribunais_destaque"):
        cobertura["tribunais_destaque"] = extra["tribunais_destaque"]
    return cobertura


def load_fontes(settings: Settings | None = None) -> dict[str, Any]:
    cfg = load_monitoramentos(settings)
    return dict(cfg.get("fontes") or {})
