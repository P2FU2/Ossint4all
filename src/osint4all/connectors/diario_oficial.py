"""Diários municipais e estaduais — Querido Diário (OK.br). Complementa DJEN e a busca web."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.graph.preview import preview_kind_for_url
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj, validate_cpf


def _query_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        return digits if validate_cnpj(digits) else None
    for ident in entity.identifiers:
        if ident.kind == "CNPJ" and validate_cnpj(ident.value):
            return only_digits(ident.value)
    name = (entity.display_name or "").strip()
    if validate_cpf(name) or name.isdigit():
        return None
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return name
    return None


def parse_gazette_rows(rows: list[dict[str, Any]], *, origin_key: str, query: str) -> ConnectorResult:
    out = ConnectorResult()
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("txt_url") or "").strip()
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        place = str(row.get("territory_name") or "").strip()
        uf = str(row.get("state_code") or "").strip()
        when = str(row.get("date") or "").strip()
        excerpt = str(row.get("excerpt") or row.get("txt_url") or "").strip()
        title = " · ".join(part for part in (place, uf, when) if part) or query
        kind = preview_kind_for_url(url)
        found = FoundEntity(
            entity_type="PUBLICATION",
            kind="URL",
            value=url,
            display_name=title[:180],
            attrs={
                "municipio": place,
                "uf": uf,
                "when": when,
                "edicao": row.get("edition"),
                "fonte": url,
                "page_url": url,
                "preview_kind": kind,
                "tipo": "pdf" if kind == "pdf" else "diario",
                "og_title": title[:220],
                "description": excerpt[:500] if excerpt else "",
            },
            confidence=0.55,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.55, attrs={"fonte": "diario_oficial"}))
        out.evidence.append(
            FoundEvidence(
                source_label="Querido Diário",
                url=url,
                snippet=(excerpt or title)[:400],
                payload={"query": query, "territory": place, "date": when},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 8:
            break
    return out


class DiarioOficialConnector:
    name = "diario_oficial"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"User-Agent": "osint4all/0.1 (querido diario)", "Accept": "application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.diario_oficial_enable, "api": "api.queridodiario.ok.org.br"}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"} and _query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.diario_oficial_enable:
            raise SkippedDisabled("Diário oficial desabilitado")
        query = _query_from_entity(entity)
        if not query:
            return ConnectorResult()
        notes: list[str] = []
        rows: list[Any] = []
        for endpoint in (
            "https://api.queridodiario.ok.org.br/gazettes",
            "https://queridodiario.ok.org.br/api/gazettes",
        ):
            resp, err = self.http.safe_request(
                "GET",
                endpoint,
                params={"querystring": query, "size": 8, "excerpt_size": 180, "number_of_excerpts": 1},
            )
            if err or resp is None:
                notes.append(f"Querido Diário: {err or 'sem resposta'}")
                continue
            try:
                data = resp.json()
            except Exception:
                notes.append("Querido Diário: resposta inválida")
                continue
            raw = data.get("gazettes") if isinstance(data, dict) else data
            if isinstance(raw, list) and raw:
                rows = raw
                break
            if isinstance(raw, list):
                rows = raw
        parsed = parse_gazette_rows(rows, origin_key=entity.canonical_key, query=query)
        if not parsed.entities:
            from urllib.parse import quote_plus

            portal = f"https://www.in.gov.br/consulta/-/buscar/dou?q={quote_plus(query)}"
            parsed.evidence.append(
                FoundEvidence(
                    source_label="DOU · Imprensa Nacional",
                    url=portal,
                    snippet=f"Busca pública no Diário Oficial da União · {query}",
                    payload={"query": query, "fallback": "in.gov.br"},
                    entity_ref=entity.canonical_key,
                )
            )
            if not notes:
                notes.append("Nenhuma edição no Querido Diário; ficou a busca do DOU.")
        parsed.notes.extend(notes)
        return parsed
