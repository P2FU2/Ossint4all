"""Configuração via ambiente."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Railway entrega postgres://; o SQLAlchemy 2 + psycopg precisa do dialeto explícito."""
    text = (url or "").strip()
    if text.startswith("postgres://"):
        text = "postgresql://" + text[len("postgres://") :]
    if text.startswith("postgresql://"):
        text = "postgresql+psycopg://" + text[len("postgresql://") :]
    return text


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///data/osint4all.db"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str) and value:
            return normalize_database_url(value)
        return value

    ui_session_secret: str = "change-me-ui-session-secret"
    ui_admin_user: str = "admin"
    ui_admin_password: str = ""
    ui_session_hours: int = 72

    expand_sync: bool = True
    expand_sync_limit: int = 25
    default_max_depth: int = 2

    cnpj_enable: bool = True
    cnpj_provider: Literal["minhareceita", "brasilapi"] = "minhareceita"
    cnpj_max_concurrency: int = 2

    datajud_enable: bool = True
    datajud_api_key: str = ""
    datajud_api_key_url: str = "https://datajud-wiki.cnj.jus.br/api-publica/acesso/"
    datajud_base_url: str = "https://api-publica.datajud.cnj.jus.br"
    datajud_max_concurrency: int = 2

    djen_enable: bool = True
    djen_base_url: str = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
    djen_http_proxy: str = ""
    djen_max_concurrency: int = 2

    tse_enable: bool = True
    transparencia_enable: bool = True
    transparencia_api_key: str = ""
    opencorporates_enable: bool = True
    opencorporates_api_token: str = ""
    wikidata_enable: bool = True
    web_search_enable: bool = True
    brave_search_api_key: str = ""
    google_cse_api_key: str = ""
    google_cse_cx: str = ""
    username_public_enable: bool = True
    crtsh_enable: bool = True

    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = 40

    schedule_cron: str = "0 7 * * 1-5"
    tz: str = "America/Sao_Paulo"
    job_max_attempts: int = 3

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()


ALL_CONNECTORS = (
    "cnpj_receita",
    "datajud",
    "djen",
    "tse",
    "transparencia",
    "opencorporates",
    "wikidata",
    "web_search",
    "username_public",
    "crtsh",
)
