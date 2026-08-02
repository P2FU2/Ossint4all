"""Comunicações / DJEN via Judit."""

from __future__ import annotations

from typing import Any

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import SkippedDisabled
from monitor_jus.sources.judit.client import JuditClient


class JuditCommunicationsService:
    def __init__(self, client: JuditClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or JuditClient(self.settings)

    def track_djen_term(self, term: str, recurrence: str = "daily") -> dict[str, Any]:
        if not self.settings.judit_enable_djen:
            raise SkippedDisabled("JUDIT_ENABLE_DJEN=false")
        body = {
            "tracking_type": "djen",
            "search": {"search_type": "term", "search_key": term},
            "recurrence": recurrence,
        }
        return self.client.create_tracking(body)
