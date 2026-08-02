"""Cliente HTTP Judit — header api-key."""

from __future__ import annotations

from typing import Any

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import SkippedDisabled
from monitor_jus.http_client import RateLimitedClient
from monitor_jus.sources.base import FonteJudicial


class JuditClient(FonteJudicial):
    name = "judit"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.http = RateLimitedClient(
            source="judit",
            max_concurrency=self.settings.judit_max_concurrency,
            timeout=40.0,
            default_headers={
                "api-key": self.settings.judit_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "api_key_configured": bool(self.settings.judit_api_key),
            "flags": self.settings.judit_flags(),
        }

    def _require(self, flag: bool, capability: str) -> None:
        if not flag:
            raise SkippedDisabled(f"Judit capability desabilitada: {capability}")
        if not self.settings.judit_api_key:
            raise SkippedDisabled("JUDIT_API_KEY não configurada")

    def create_request(self, body: dict[str, Any]) -> dict[str, Any]:
        self._require(self.settings.judit_enable_historical_search or True, "requests")
        # historical flag gated by caller for OAB/CPF; base requests endpoint always needs key
        if not self.settings.judit_api_key:
            raise SkippedDisabled("JUDIT_API_KEY não configurada")
        url = f"{self.settings.judit_requests_base_url.rstrip('/')}/requests"
        resp = self.http.request("POST", url, json=body, operation="create_request")
        resp.raise_for_status()
        return resp.json()

    def get_request(self, request_id: str) -> dict[str, Any]:
        if not self.settings.judit_api_key:
            raise SkippedDisabled("JUDIT_API_KEY não configurada")
        url = f"{self.settings.judit_requests_base_url.rstrip('/')}/requests/{request_id}"
        resp = self.http.request("GET", url, operation="get_request")
        resp.raise_for_status()
        return resp.json()

    def get_lawsuit(self, numero_cnj: str) -> dict[str, Any]:
        if not self.settings.judit_api_key:
            raise SkippedDisabled("JUDIT_API_KEY não configurada")
        # endpoint convencional — validar no Postman contratado
        url = f"{self.settings.judit_requests_base_url.rstrip('/')}/lawsuits/{numero_cnj}"
        resp = self.http.request("GET", url, operation="get_lawsuit")
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    def create_tracking(self, body: dict[str, Any]) -> dict[str, Any]:
        self._require(self.settings.judit_enable_process_tracking or self.settings.judit_enable_document_tracking, "tracking")
        url = f"{self.settings.judit_tracking_base_url.rstrip('/')}/tracking"
        resp = self.http.request("POST", url, json=body, operation="create_tracking")
        resp.raise_for_status()
        return resp.json()

    def list_trackings(self) -> list[dict[str, Any]]:
        if not self.settings.judit_api_key:
            raise SkippedDisabled("JUDIT_API_KEY não configurada")
        url = f"{self.settings.judit_tracking_base_url.rstrip('/')}/tracking"
        resp = self.http.request("GET", url, operation="list_tracking")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return list(data.get("items") or data.get("data") or [])

    def cancel_tracking(self, tracking_id: str) -> None:
        url = f"{self.settings.judit_tracking_base_url.rstrip('/')}/tracking/{tracking_id}"
        resp = self.http.request("DELETE", url, operation="cancel_tracking")
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()
