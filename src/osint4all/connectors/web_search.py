"""Busca web: Brave, Google CSE ou SearXNG público (sem chave)."""

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

# Instâncias públicas que costumam expor /search?format=json. A lista muda; falha de uma não derruba a consulta.
DEFAULT_SEARXNG_INSTANCES = (
    "https://searx.be",
    "https://priv.au",
    "https://searx.tiekoetter.com",
    "https://search.ononoki.org",
    "https://opnxng.com",
    "https://search.sapti.me",
    "https://searxng.site",
)


def searxng_bases(settings: Settings) -> list[str]:
    seen: list[str] = []
    extras = [part.strip() for part in (settings.searxng_instances or "").split(",") if part.strip()]
    for raw in (settings.searxng_url, *extras, *DEFAULT_SEARXNG_INSTANCES):
        url = (raw or "").strip().rstrip("/")
        if url and url not in seen:
            seen.append(url)
    return seen


def web_search_ready(settings: Settings) -> bool:
    if not settings.web_search_enable:
        return False
    if settings.brave_search_api_key:
        return True
    if settings.google_cse_api_key and settings.google_cse_cx:
        return True
    return bool(settings.searxng_enable and searxng_bases(settings))


def parse_web_hits(hits: list[dict[str, Any]], *, origin_key: str, source: str = "Busca web (API oficial)") -> ConnectorResult:
    out = ConnectorResult()
    seen_owners: set[str] = set()
    vehicle_hints: list[str] = []
    for hit in hits[:10]:
        url = str(hit.get("url") or hit.get("link") or "")
        title = str(hit.get("title") or url)
        snippet = str(hit.get("description") or hit.get("snippet") or hit.get("content") or "")
        if not url:
            continue
        found = FoundEntity(
            entity_type="PUBLICATION",
            kind="URL",
            value=url,
            display_name=title[:160],
            attrs={"snippet": snippet, "engine": hit.get("engine") or ""},
            confidence=0.4,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.4))
        out.evidence.append(
            FoundEvidence(
                source_label=source,
                url=url,
                snippet=snippet or title,
                payload={"title": title, "engine": hit.get("engine")},
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


def parse_searxng_payload(data: dict[str, Any], *, origin_key: str, instance: str = "") -> ConnectorResult:
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        rows = []
    hits = [
        {
            "url": row.get("url"),
            "title": row.get("title"),
            "content": row.get("content") or row.get("snippet"),
            "engine": row.get("engine"),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    label = f"SearXNG público{f' · {instance}' if instance else ''}"
    out = parse_web_hits(hits, origin_key=origin_key, source=label)
    if hits:
        out.notes.append(label)
    return out


class WebSearchConnector:
    name = "web_search"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=14.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1 (investigative journalism)"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.web_search_enable,
            "brave": bool(self.settings.brave_search_api_key),
            "google_cse": bool(self.settings.google_cse_api_key and self.settings.google_cse_cx),
            "searxng": bool(self.settings.searxng_enable),
            "searxng_instances": searxng_bases(self.settings)[:4] if self.settings.searxng_enable else [],
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
        return self.search(query, entity.canonical_key)

    def search(self, query: str, origin_key: str) -> ConnectorResult:
        if self.settings.brave_search_api_key:
            result = self._brave(query, origin_key)
            if result.entities or result.evidence:
                return result
        if self.settings.google_cse_api_key and self.settings.google_cse_cx:
            result = self._google(query, origin_key)
            if result.entities or result.evidence:
                return result
        if self.settings.searxng_enable:
            result = self._searxng(query, origin_key)
            if result.entities or result.evidence or result.notes:
                return result
        raise FailedAuthentication(
            "Nenhum backend de busca respondeu. Tente SEARXNG_URL (sua instância) ou BRAVE_SEARCH_API_KEY / Google CSE."
        )

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
        return parse_web_hits(hits, origin_key=origin_key, source="Brave Search")

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
        return parse_web_hits(hits, origin_key=origin_key, source="Google CSE")

    def _searxng(self, query: str, origin_key: str) -> ConnectorResult:
        last = "nenhuma instância respondeu JSON"
        for base in searxng_bases(self.settings)[:6]:
            try:
                resp = self.http.request(
                    "GET",
                    f"{base}/search",
                    params={"q": query, "format": "json", "categories": "general", "language": "pt-BR"},
                    allow_404=True,
                    max_retries=1,
                )
            except Exception as exc:  # noqa: BLE001
                last = f"{base}: {exc}"
                continue
            ctype = (resp.headers.get("content-type") or "").lower()
            if resp.status_code >= 400:
                last = f"{base} HTTP {resp.status_code}"
                continue
            if "json" not in ctype and not (resp.content or b"").lstrip().startswith(b"{"):
                last = f"{base} sem API JSON"
                continue
            try:
                data = resp.json()
            except Exception:
                last = f"{base} JSON inválido"
                continue
            if not isinstance(data, dict):
                last = f"{base} payload inesperado"
                continue
            parsed = parse_searxng_payload(data, origin_key=origin_key, instance=base)
            if parsed.entities:
                return parsed
            last = f"{base} sem resultados"
        return ConnectorResult(notes=[f"SearXNG público: {last}"])
