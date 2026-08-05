"""Cliente HTTP da Comunica API (DJEN)."""

from __future__ import annotations

from typing import Any

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import (
    FailedAuthentication,
    FailedRateLimit,
    FailedSource,
    SkippedDisabled,
)
from monitor_jus.http_client import RateLimitedClient
from monitor_jus.logging_setup import get_logger
from monitor_jus.sources.djen.criteria import DjenSearchCriteria
from monitor_jus.sources.djen.params import build_query_params, djen_base_url

logger = get_logger(__name__)


class DjenClient:
    name = "djen"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.http = RateLimitedClient(
            source="djen",
            max_concurrency=self.settings.djen_max_concurrency,
            timeout=45.0,
            default_headers={
                "Accept": "application/json",
                "User-Agent": "monitor-jus/1.0",
            },
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.djen_enable,
            "base_url": djen_base_url(),
        }

    def search(self, criteria: DjenSearchCriteria) -> dict[str, Any]:
        if not self.settings.djen_enable:
            raise SkippedDisabled("DJEN desabilitado")
        params = build_query_params(criteria)
        url = djen_base_url()
        try:
            resp = self.http.request(
                "GET",
                url,
                params=params,
                operation="comunicacao",
            )
        except FailedAuthentication as exc:
            # 403 pode ser CloudFront / geo
            raise FailedAuthentication(f"DJEN 403/auth: {exc}") from exc
        except FailedRateLimit:
            raise
        except Exception as exc:  # noqa: BLE001
            body_hint = str(exc)
            if "CloudFront" in body_hint or "403" in body_hint:
                raise FailedAuthentication(f"DJEN bloqueio CloudFront/403: {exc}") from exc
            raise FailedSource(f"DJEN falhou: {exc}") from exc

        # CloudFront HTML block pages
        ctype = (resp.headers.get("content-type") or "").lower()
        if "text/html" in ctype and "cloudfront" in (resp.text or "").lower():
            raise FailedAuthentication("DJEN bloqueado por CloudFront")

        if resp.status_code == 403:
            raise FailedAuthentication("DJEN HTTP 403")
        if resp.status_code == 429:
            raise FailedRateLimit("DJEN HTTP 429")
        if resp.status_code >= 500:
            raise FailedSource(f"DJEN HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise FailedSource(f"DJEN HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise FailedSource(f"DJEN JSON inválido: {exc}") from exc

        return self._normalize_response(data)

    def search_all_pages(
        self,
        criteria: DjenSearchCriteria,
        *,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = criteria.page
        for _ in range(max_pages):
            page_criteria = DjenSearchCriteria(
                text=criteria.text,
                lawyer_name=criteria.lawyer_name,
                oab_number=criteria.oab_number,
                oab_state=criteria.oab_state,
                process_number=criteria.process_number,
                court=criteria.court,
                available_from=criteria.available_from,
                available_until=criteria.available_until,
                page=page,
                size=criteria.size,
            )
            data = self.search(page_criteria)
            batch = data.get("items") or []
            items.extend(batch)
            total = data.get("total")
            if not batch:
                break
            if total is not None and len(items) >= int(total):
                break
            if len(batch) < criteria.size:
                break
            page += 1
        return items

    def _normalize_response(self, data: Any) -> dict[str, Any]:
        from monitor_jus.config import load_yaml

        cfg = load_yaml(self.settings.config_path("djen_param_map.yaml")) or {}
        resp_cfg = cfg.get("response") or {}
        items_key = resp_cfg.get("items_key") or "items"
        total_key = resp_cfg.get("total_key") or "count"

        if isinstance(data, list):
            return {"items": data, "total": len(data), "raw": data}

        if not isinstance(data, dict):
            return {"items": [], "total": 0, "raw": data}

        items = data.get(items_key)
        if items is None:
            for alt in ("content", "data", "comunicacoes", "items"):
                if isinstance(data.get(alt), list):
                    items = data[alt]
                    break
        if not isinstance(items, list):
            items = []
        total = data.get(total_key, data.get("total", len(items)))
        return {"items": items, "total": total, "raw": data}
