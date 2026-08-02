"""Descoberta / consultas assíncronas Judit."""

from __future__ import annotations

from typing import Any

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import SkippedDisabled
from monitor_jus.sources.judit.client import JuditClient
from monitor_jus.validators import normalize_oab_numero


def oab_search_key(numero: str, seccional: str) -> str:
    """Formato Judit: {numero}{UF}, ex.: 138094SP."""
    return f"{normalize_oab_numero(numero)}{(seccional or '').strip().upper()}"


class JuditRequestsService:
    def __init__(self, client: JuditClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or JuditClient(self.settings)

    def search_by_oab(self, numero: str, seccional: str) -> dict[str, Any]:
        if not self.settings.judit_enable_oab:
            raise SkippedDisabled("JUDIT_ENABLE_OAB=false")
        if not self.settings.judit_enable_historical_search:
            raise SkippedDisabled("JUDIT_ENABLE_HISTORICAL_SEARCH=false")
        body = {
            "search": {
                "search_type": "oab",
                "search_key": oab_search_key(numero, seccional),
            },
            "with_attachments": bool(self.settings.judit_enable_attachments),
        }
        return self.client.create_request(body)

    def search_by_document(self, document: str, doc_type: str = "cpf") -> dict[str, Any]:
        if not self.settings.judit_enable_cpf_cnpj:
            raise SkippedDisabled("JUDIT_ENABLE_CPF_CNPJ=false")
        if not self.settings.judit_enable_historical_search:
            raise SkippedDisabled("JUDIT_ENABLE_HISTORICAL_SEARCH=false")
        body = {
            "search": {
                "search_type": doc_type,
                "search_key": document,
            }
        }
        return self.client.create_request(body)

    def search_by_name(self, name: str) -> dict[str, Any]:
        if not self.settings.judit_enable_name:
            raise SkippedDisabled("JUDIT_ENABLE_NAME=false")
        body = {"search": {"search_type": "name", "search_key": name}}
        return self.client.create_request(body)

    def search_by_cnj(self, numero_cnj: str) -> dict[str, Any]:
        body = {"search": {"search_type": "lawsuit_cnj", "search_key": numero_cnj}}
        return self.client.create_request(body)
