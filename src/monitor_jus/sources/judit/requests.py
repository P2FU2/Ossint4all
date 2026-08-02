"""Descoberta / consultas assíncronas Judit."""

from __future__ import annotations

import time
from typing import Any

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import FailedSource, FailedTimeout, SkippedDisabled
from monitor_jus.logging_setup import get_logger
from monitor_jus.sources.judit.client import JuditClient
from monitor_jus.sources.judit.schemas import extract_request_id
from monitor_jus.validators import normalize_oab_numero

logger = get_logger(__name__)


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
        return self.create_and_collect(body)

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
        return self.create_and_collect(body)

    def search_by_name(self, name: str) -> dict[str, Any]:
        if not self.settings.judit_enable_name:
            raise SkippedDisabled("JUDIT_ENABLE_NAME=false")
        body = {"search": {"search_type": "name", "search_key": name}}
        return self.create_and_collect(body)

    def search_by_cnj(self, numero_cnj: str) -> dict[str, Any]:
        body = {"search": {"search_type": "lawsuit_cnj", "search_key": numero_cnj}}
        return self.create_and_collect(body)

    def create_and_collect(
        self,
        body: dict[str, Any],
        *,
        timeout_seconds: float = 120.0,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """POST /requests → poll até completed → GET /responses (paginado)."""
        created = self.client.create_request(body)
        request_id = extract_request_id(created)
        if not request_id:
            # resposta síncrona rara — devolve o payload direto
            return {"request": created, "page_data": [created], "status": "sync"}

        deadline = time.monotonic() + timeout_seconds
        status = "pending"
        last: dict[str, Any] = created
        while time.monotonic() < deadline:
            last = self.client.get_request(request_id)
            status = str(last.get("status") or "").lower()
            if status in {"completed", "complete", "done", "finished"}:
                break
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise FailedSource(f"judit request {request_id} status={status}")
            time.sleep(poll_interval)
        else:
            raise FailedTimeout(f"judit request {request_id} timeout ({timeout_seconds}s)")

        page_data: list[Any] = []
        page = 1
        page_count = 1
        while page <= page_count and page <= 50:
            chunk = self.client.list_responses(request_id, page=page, page_size=100)
            page_count = int(chunk.get("page_count") or chunk.get("all_pages_count") or 1)
            items = chunk.get("page_data") or chunk.get("data") or []
            if isinstance(items, list):
                page_data.extend(items)
            if not items:
                break
            page += 1

        logger.info(
            "judit_request_collected",
            extra={"extra": {"request_id": request_id, "responses": len(page_data), "status": status}},
        )
        return {
            "request_id": request_id,
            "request": last,
            "status": status,
            "page_data": page_data,
        }
