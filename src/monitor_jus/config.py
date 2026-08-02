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

    judit_api_key: str = ""
    judit_requests_base_url: str = "https://requests.production.judit.io"
    judit_tracking_base_url: str = "https://tracking.production.judit.io"
    judit_enable_historical_search: bool = False
    judit_enable_oab: bool = False
    judit_enable_cpf_cnpj: bool = False
    judit_enable_name: bool = False
    judit_enable_process_tracking: bool = False
    judit_enable_document_tracking: bool = False
    judit_enable_djen: bool = False
    judit_enable_attachments: bool = False
    judit_max_concurrency: int = 3

    judit_webhook_auth_mode: Literal["none", "static_token", "hmac", "ip_allowlist"] = (
        "static_token"
    )
    judit_webhook_token: str = ""
    judit_webhook_signature_header: str = ""
    judit_webhook_signature_algorithm: str = "sha256"
    judit_webhook_allowed_ips: str = ""

    datajud_enable: bool = True
    datajud_mode: Literal["selective", "confirm_and_fallback", "fallback_only", "off"] = (
        "selective"
    )
    datajud_api_key: str = ""
    datajud_api_key_url: str = "https://datajud-wiki.cnj.jus.br/api-publica/acesso/"
    datajud_max_concurrency: int = 3
    datajud_base_url: str = "https://api-publica.datajud.cnj.jus.br"

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

    # Painel web (login humano — separado do API_TRIGGER_TOKEN)
    ui_session_secret: str = "change-me-ui-session-secret"
    ui_admin_user: str = "admin"
    ui_admin_password: str = ""
    ui_session_hours: int = 72

    @field_validator("judit_webhook_allowed_ips", mode="before")
    @classmethod
    def _ips(cls, v: Any) -> str:
        return v or ""

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def openrouter_fallback_list(self) -> list[str]:
        return [m.strip() for m in self.openrouter_fallback_models.split(",") if m.strip()]

    @property
    def webhook_allowed_ip_list(self) -> list[str]:
        return [i.strip() for i in self.judit_webhook_allowed_ips.split(",") if i.strip()]

    def judit_flags(self) -> dict[str, bool]:
        return {
            "historical_search": self.judit_enable_historical_search,
            "oab": self.judit_enable_oab,
            "cpf_cnpj": self.judit_enable_cpf_cnpj,
            "name": self.judit_enable_name,
            "process_tracking": self.judit_enable_process_tracking,
            "document_tracking": self.judit_enable_document_tracking,
            "djen": self.judit_enable_djen,
            "attachments": self.judit_enable_attachments,
        }

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
