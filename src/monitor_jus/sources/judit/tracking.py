"""Monitoramento contínuo Judit."""

from __future__ import annotations

from typing import Any

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import SkippedDisabled
from monitor_jus.sources.judit.client import JuditClient


class JuditTrackingService:
    def __init__(self, client: JuditClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or JuditClient(self.settings)

    def track_process(self, numero_cnj: str, recurrence: str = "daily") -> dict[str, Any]:
        if not self.settings.judit_enable_process_tracking:
            raise SkippedDisabled("JUDIT_ENABLE_PROCESS_TRACKING=false")
        body = {
            "tracking_type": "lawsuit",
            "search": {"search_type": "lawsuit_cnj", "search_key": numero_cnj},
            "recurrence": recurrence,
        }
        return self.client.create_tracking(body)

    def track_document(self, document: str, doc_type: str = "cpf", recurrence: str = "daily") -> dict[str, Any]:
        if not self.settings.judit_enable_document_tracking:
            raise SkippedDisabled("JUDIT_ENABLE_DOCUMENT_TRACKING=false")
        body = {
            "tracking_type": "document",
            "search": {"search_type": doc_type, "search_key": document},
            "recurrence": recurrence,
        }
        return self.client.create_tracking(body)

    def track_oab(self, numero: str, seccional: str, recurrence: str = "daily") -> dict[str, Any]:
        if not self.settings.judit_enable_document_tracking and not self.settings.judit_enable_oab:
            raise SkippedDisabled("tracking OAB desabilitado")
        body = {
            "tracking_type": "oab",
            "search": {
                "search_type": "oab",
                "lawyer_oab": numero,
                "lawyer_state": seccional.upper(),
            },
            "recurrence": recurrence,
        }
        return self.client.create_tracking(body)
