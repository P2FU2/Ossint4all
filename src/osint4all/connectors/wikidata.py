"""Conector Wikidata — busca pública e cargos."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key


def parse_wikidata_search(results: list[dict[str, Any]], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for item in results[:8]:
        qid = str(item.get("id") or "")
        label = str(item.get("label") or item.get("title") or qid)
        desc = str(item.get("description") or "")
        url = f"https://www.wikidata.org/wiki/{qid}" if qid else "https://www.wikidata.org/"
        found = FoundEntity(
            entity_type="PUBLICATION" if item.get("concepturi") else "PERSON",
            kind="URL",
            value=url,
            display_name=f"{label} ({qid})" if qid else label,
            attrs={"wikidata_id": qid, "description": desc},
            confidence=0.5,
        )
        # Pessoa/organização descrita no Wikidata vira PUBLICATION (ficha) ligada à origem
        found.entity_type = "PUBLICATION"
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5))
        out.evidence.append(
            FoundEvidence(
                source_label="Wikidata",
                url=url,
                snippet=f"{label} — {desc}".strip(" —"),
                payload={"id": qid, "label": label, "description": desc},
                entity_ref=ref,
            )
        )
    return out


class WikidataConnector:
    name = "wikidata"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=25.0,
            default_headers={"User-Agent": "osint4all/0.1 (investigative journalism)"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.wikidata_enable}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"} and bool(entity.display_name)

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.wikidata_enable:
            raise SkippedDisabled("Wikidata desabilitado")
        resp = self.http.request(
            "GET",
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": entity.display_name,
                "language": "pt",
                "uselang": "pt",
                "format": "json",
                "limit": 8,
            },
        )
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"Wikidata HTTP {resp.status_code}"])
        data = resp.json()
        results = data.get("search") if isinstance(data, dict) else []
        if not results:
            fallback = self.http.request(
                "GET",
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "search": entity.display_name,
                    "language": "en",
                    "uselang": "en",
                    "format": "json",
                    "limit": 8,
                },
            )
            if fallback.status_code < 400:
                extra = fallback.json()
                results = extra.get("search") if isinstance(extra, dict) else []
        parsed = parse_wikidata_search(results or [], origin_key=entity.canonical_key)
        if not parsed.entities:
            parsed.notes.append("Wikidata sem ficha pública para este nome.")
        return parsed
