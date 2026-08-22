"""OpenSanctions — PEP e sanções internacionais, busca pública sem chave."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj


def _query_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        if validate_cnpj(digits):
            return digits
    name = (entity.display_name or "").strip()
    if entity.entity_type in {"PERSON", "ORG"} and len(name) >= 4:
        return name
    return None


def _rows_from_payload(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("results"), list):
        return data["results"]
    responses = data.get("responses")
    if isinstance(responses, dict):
        for block in responses.values():
            if isinstance(block, dict) and isinstance(block.get("results"), list):
                return block["results"]
    return []


def parse_opensanctions_hits(rows: list[Any], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows:
        if not isinstance(row, dict):
            continue
        caption = str(row.get("caption") or row.get("name") or "").strip()
        ident = str(row.get("id") or "").strip()
        if not caption or not ident:
            continue
        schema = str(row.get("schema") or "")
        datasets = row.get("datasets") or row.get("datasets") or []
        if not isinstance(datasets, list):
            datasets = []
        topics = []
        props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        raw_topics = props.get("topics") if isinstance(props, dict) else []
        if isinstance(raw_topics, list):
            topics = [str(t) for t in raw_topics[:8]]
        url = f"https://www.opensanctions.org/entities/{ident}"
        kind = "PERSON" if schema.lower() in {"person"} else "ORG"
        found = FoundEntity(
            entity_type=kind,
            kind="URL",
            value=url,
            display_name=caption[:180],
            attrs={
                "schema": schema,
                "fonte": "opensanctions",
                "datasets": [str(d) for d in datasets[:8]],
                "topics": topics,
                "tipo": "sancao" if "sanction" in " ".join(topics).casefold() or any("sanction" in str(d).casefold() for d in datasets) else "pep",
            },
            confidence=0.55,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="SANCAO", confidence=0.55, attrs={"fonte": "opensanctions"}))
        out.evidence.append(
            FoundEvidence(
                source_label="OpenSanctions",
                url=url,
                snippet=f"{schema}: {caption}"[:400],
                payload={"id": ident, "schema": schema, "datasets": datasets[:8], "topics": topics},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 8:
            break
    return out


class OpensanctionsPublicConnector:
    name = "opensanctions_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1 (opensanctions public search)"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.opensanctions_public_enable, "via": "api.opensanctions.org", "key": ""}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"} and _query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.opensanctions_public_enable:
            raise SkippedDisabled("OpenSanctions desabilitado")
        query = _query_from_entity(entity)
        if not query:
            return ConnectorResult()
        resp, err = self.http.safe_request(
            "GET",
            "https://api.opensanctions.org/search/default",
            params={"q": query, "limit": 8},
            max_retries=1,
        )
        if err or resp is None or (resp is not None and resp.status_code in (401, 403)):
            return self._html_search(query, entity.canonical_key, note=err or "API pediu chave")
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult(notes=["OpenSanctions: resposta inválida"])
        parsed = parse_opensanctions_hits(_rows_from_payload(data), origin_key=entity.canonical_key)
        if not parsed.entities:
            parsed.merge(self._html_search(query, entity.canonical_key, note="API vazia"))
        return parsed

    def _html_search(self, query: str, origin_key: str, *, note: str = "") -> ConnectorResult:
        from urllib.parse import quote_plus

        from osint4all.connectors.html_public import parse_opensanctions_html

        portal = f"https://www.opensanctions.org/search/?q={quote_plus(query)}"
        resp, err = self.http.safe_request("GET", portal, max_retries=1)
        if resp is not None and resp.status_code < 400:
            parsed = parse_opensanctions_html(resp.text or "", origin_key=origin_key)
            if parsed.entities:
                return parsed
        out = ConnectorResult(notes=[f"OpenSanctions: {note or err or 'sem resultados'}"])
        out.evidence.append(
            FoundEvidence(
                source_label="OpenSanctions",
                url=portal,
                snippet=f"Busca pública gratuita · {query}",
                payload={"query": query, "via": "scraper"},
                entity_ref=origin_key,
            )
        )
        return out
