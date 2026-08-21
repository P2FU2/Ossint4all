"""GLEIF — identificador LEI de pessoa jurídica, API pública sem chave."""

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


def _query_from_entity(entity: Entity) -> tuple[str, str] | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        if validate_cnpj(digits):
            return "registered", digits
    name = (entity.display_name or str((entity.attrs or {}).get("razao_social") or "")).strip()
    if entity.entity_type == "ORG" and len(name) >= 3:
        return "name", name
    return None


def parse_gleif_records(rows: list[Any], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else row
        lei = str(attrs.get("lei") or row.get("id") or "").strip()
        entity_block = attrs.get("entity") if isinstance(attrs.get("entity"), dict) else {}
        legal = entity_block.get("legalName") if isinstance(entity_block.get("legalName"), dict) else {}
        nome = str(legal.get("name") or entity_block.get("legalName") or "").strip()
        registered = str(entity_block.get("registeredAs") or "").strip()
        jurisdiction = str(entity_block.get("jurisdiction") or "")
        if not lei:
            continue
        url = f"https://search.gleif.org/#/record/{lei}"
        found = FoundEntity(
            entity_type="ORG",
            kind="URL",
            value=url,
            display_name=(nome or lei)[:180],
            attrs={
                "lei": lei,
                "razao_social": nome,
                "registered_as": registered,
                "jurisdicao": jurisdiction,
                "fonte": "gleif",
                "tipo": "lei",
            },
            confidence=0.7,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="IDENTIDADE", confidence=0.65, attrs={"lei": lei}))
        digits = only_digits(registered)
        if validate_cnpj(digits) and canonical_key("CNPJ", digits) != origin_key:
            out.entities.append(
                FoundEntity(entity_type="ORG", kind="CNPJ", value=digits, display_name=nome or digits, attrs={"lei": lei}, confidence=0.75)
            )
            out.edges.append(
                FoundEdge(from_ref=origin_key, to_ref=canonical_key("CNPJ", digits), rel_type="IDENTIDADE", confidence=0.7, attrs={"lei": lei})
            )
        out.evidence.append(
            FoundEvidence(
                source_label="GLEIF · LEI",
                url=url,
                snippet=f"{lei} · {nome} {jurisdiction}".strip()[:400],
                payload={"lei": lei, "name": nome, "registeredAs": registered, "jurisdiction": jurisdiction},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 8:
            break
    return out


class GleifPublicConnector:
    name = "gleif_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={
                "Accept": "application/vnd.api+json",
                "User-Agent": "osint4all/0.1 (gleif public)",
            },
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.gleif_public_enable, "via": "api.gleif.org", "key": ""}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type == "ORG" and _query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.gleif_public_enable:
            raise SkippedDisabled("GLEIF desabilitado")
        query = _query_from_entity(entity)
        if not query:
            return ConnectorResult()
        kind, value = query
        params: dict[str, Any] = {"page[size]": 5}
        if kind == "registered":
            params["filter[entity.registeredAs]"] = value
        else:
            params["filter[entity.legalName]"] = value
        try:
            resp = self.http.request(
                "GET",
                "https://api.gleif.org/api/v1/lei-records",
                params=params,
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult(notes=["GLEIF indisponível nesta rodada"])
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"GLEIF HTTP {resp.status_code}"])
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        rows = data.get("data") if isinstance(data, dict) else data
        parsed = parse_gleif_records(rows if isinstance(rows, list) else [], origin_key=entity.canonical_key)
        if not parsed.entities:
            parsed.notes.append("Nenhum LEI GLEIF para esta razão/CNPJ.")
        return parsed
