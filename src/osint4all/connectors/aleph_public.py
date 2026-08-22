"""Aleph / OCCRP — pessoas, empresas e documentos em datasets investigativos públicos."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj, validate_cpf


def _query_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        return digits if validate_cnpj(digits) else None
    name = (entity.display_name or "").strip()
    if validate_cpf(name) or name.isdigit():
        return None
    parts = [p for p in name.split() if p]
    if len(parts) >= 2 or entity.entity_type == "ORG":
        return name if len(name) >= 3 else None
    return None


def parse_aleph_results(rows: list[Any], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows:
        if not isinstance(row, dict):
            continue
        caption = str(row.get("caption") or row.get("name") or "").strip()
        schema = str(row.get("schema") or "")
        ident = str(row.get("id") or "")
        if not caption or not ident:
            continue
        url = f"https://aleph.occrp.org/entities/{ident}"
        kind = "ORG" if schema.lower() in {"company", "organization", "legalentity"} else "PUBLICATION"
        if schema.lower() in {"person", "legalentity"} and " " in caption:
            kind = "PERSON" if schema.lower() == "person" else kind
        found = FoundEntity(
            entity_type="PUBLICATION" if kind == "PUBLICATION" else kind,
            kind="URL",
            value=url,
            display_name=caption[:180],
            attrs={"schema": schema, "fonte": "aleph", "aleph_id": ident},
            confidence=0.5,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5, attrs={"fonte": "aleph"}))
        out.evidence.append(
            FoundEvidence(
                source_label="Aleph / OCCRP",
                url=url,
                snippet=f"{schema}: {caption}"[:400],
                payload={"id": ident, "schema": schema, "caption": caption},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 8:
            break
    return out


class AlephPublicConnector:
    name = "aleph_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"User-Agent": "osint4all/0.1 (aleph public search)", "Accept": "application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.aleph_public_enable, "via": "aleph.occrp.org"}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"} and _query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.aleph_public_enable:
            raise SkippedDisabled("Aleph desabilitado")
        query = _query_from_entity(entity)
        if not query:
            return ConnectorResult()
        resp, err = self.http.safe_request(
            "GET",
            "https://aleph.occrp.org/api/2/entities",
            params={"q": query, "limit": 8},
            max_retries=1,
        )
        if err or resp is None:
            return ConnectorResult(notes=[f"Aleph: {err or 'sem resposta'}"])
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult(notes=["Aleph: resposta inválida"])
        rows = data.get("results") if isinstance(data, dict) else None
        parsed = parse_aleph_results(rows if isinstance(rows, list) else [], origin_key=entity.canonical_key)
        if not parsed.entities:
            parsed.notes.append("Nenhum documento Aleph/OCCRP com esse termo.")
        return parsed
