"""Consulta de processos na base Judit."""

from __future__ import annotations

from typing import Any

from monitor_jus.sources.judit.client import JuditClient
from monitor_jus.validators import normalize_cnj


class JuditLawsuitsService:
    def __init__(self, client: JuditClient | None = None) -> None:
        self.client = client or JuditClient()

    def get_full_process(self, numero: str) -> dict[str, Any]:
        parts = normalize_cnj(numero)
        key = parts.numero_digits if parts else numero
        return self.client.get_lawsuit(key)
