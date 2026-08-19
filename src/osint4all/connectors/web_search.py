"""Busca web via Brave Search ou Google Programmable Search."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.plate_public import extract_owner_mentions, extract_vehicle_mentions, parse_declared_owner
from osint4all.db.models import Entity
from osint4all.exceptions import FailedAuthentication, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.validators import format_plate


def parse_web_hits(hits: list[dict[str, Any]], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    seen_owners: set[str] = set()
    vehicle_hints: list[str] = []
    for hit in hits[:10]:
        url = str(hit.get("url") or hit.get("link") or "")
        title = str(hit.get("title") or url)
        snippet = str(hit.get("description") or hit.get("snippet") or "")
        if not url:
            continue
        found = FoundEntity(
            entity_type="PUBLICATION",
            kind="URL",
            value=url,
            display_name=title[:160],
            attrs={"snippet": snippet},
            confidence=0.4,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.4))
        out.evidence.append(
            FoundEvidence(
                source_label="Busca web (API oficial)",
                url=url,
                snippet=snippet or title,
                payload={"title": title},
                entity_ref=ref,
            )
        )
        blob = f"{title} {snippet}"
        if origin_key.startswith("plate:"):
            for name in extract_owner_mentions(blob):
                key = name.casefold()
                if key in seen_owners:
                    continue
                seen_owners.add(key)
                out.merge(parse_declared_owner(origin_key, owner_name=name, source="mencao_publica", confidence=0.32))
            for model in extract_vehicle_mentions(blob):
                if model not in vehicle_hints:
                    vehicle_hints.append(model)
    if origin_key.startswith("plate:") and vehicle_hints:
        plate = origin_key.split(":", 1)[1]
        out.entities.append(
            FoundEntity(
                entity_type="VEHICLE",
                kind="PLATE",
                value=format_plate(plate),
                display_name=format_plate(plate),
                attrs={"mencoes_modelo": vehicle_hints},
                confidence=0.35,
            )
        )
    return out


class WebSearchConnector:
    name = "web_search"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=20.0,
            default_headers={"User-Agent": "osint4all/0.1"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.web_search_enable,
            "brave": bool(self.settings.brave_search_api_key),
            "google_cse": bool(self.settings.google_cse_api_key and self.settings.google_cse_cx),
        }

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG", "VEHICLE", "ASSET"} and bool(entity.display_name)

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.web_search_enable:
            raise SkippedDisabled("busca web desabilitada")
        query = entity.display_name
        if entity.canonical_key.startswith("plate:"):
            plate = entity.canonical_key.split(":", 1)[1]
            pretty = format_plate(plate)
            query = f'"{plate}" OR "{pretty}" (placa OR veículo OR proprietário)'
        if self.settings.brave_search_api_key:
            return self._brave(query, entity.canonical_key)
        if self.settings.google_cse_api_key and self.settings.google_cse_cx:
            return self._google(query, entity.canonical_key)
        raise FailedAuthentication("Configure BRAVE_SEARCH_API_KEY ou GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX")

    def _brave(self, query: str, origin_key: str) -> ConnectorResult:
        resp = self.http.request(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": self.settings.brave_search_api_key, "Accept": "application/json"},
            params={"q": query, "count": 10},
        )
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"Brave HTTP {resp.status_code}"])
        data = resp.json()
        hits = ((data.get("web") or {}).get("results")) or []
        return parse_web_hits(hits, origin_key=origin_key)

    def _google(self, query: str, origin_key: str) -> ConnectorResult:
        resp = self.http.request(
            "GET",
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self.settings.google_cse_api_key,
                "cx": self.settings.google_cse_cx,
                "q": query,
                "num": 10,
            },
        )
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"Google CSE HTTP {resp.status_code}"])
        data = resp.json()
        hits = data.get("items") or []
        return parse_web_hits(hits, origin_key=origin_key)
