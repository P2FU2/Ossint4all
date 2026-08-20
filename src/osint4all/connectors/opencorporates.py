"""Conector OpenCorporates — empresas fora do BR / nomes globais."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits


def parse_opencorporates(results: list[dict[str, Any]], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in results[:12]:
        company = row.get("company") if isinstance(row, dict) else None
        if not isinstance(company, dict):
            continue
        name = str(company.get("name") or "").strip()
        company_number = str(company.get("company_number") or "")
        jur = str(company.get("jurisdiction_code") or "")
        oc_url = str(company.get("opencorporates_url") or "")
        if not name:
            continue
        kind = "CNPJ" if jur.startswith("br") and len(only_digits(company_number)) == 14 else "NAME"
        value = only_digits(company_number) if kind == "CNPJ" else name
        found = FoundEntity(
            entity_type="ORG",
            kind=kind,
            value=value,
            display_name=name,
            attrs={"jurisdiction": jur, "company_number": company_number},
            confidence=0.55,
        )
        out.entities.append(found)
        ref = canonical_key(kind, value)
        if ref != origin_key:
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5))
        out.evidence.append(
            FoundEvidence(
                source_label="OpenCorporates",
                url=oc_url or "https://opencorporates.com/",
                snippet=f"{name} · {jur} · {company_number}",
                payload={"jurisdiction": jur, "company_number": company_number},
                entity_ref=ref,
            )
        )
    return out


class OpenCorporatesConnector:
    name = "opencorporates"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.opencorporates_enable,
            "token_configured": bool(self.settings.opencorporates_api_token),
        }

    def accepts(self, entity: Entity) -> bool:
        key = str(entity.canonical_key or "")
        return entity.entity_type == "ORG" or key.startswith("cnpj:")

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.opencorporates_enable:
            raise SkippedDisabled("OpenCorporates desabilitado")
        params: dict[str, Any] = {"q": entity.display_name, "per_page": 10}
        if self.settings.opencorporates_api_token:
            params["api_token"] = self.settings.opencorporates_api_token
        resp = self.http.request(
            "GET",
            "https://api.opencorporates.com/v0.4/companies/search",
            params=params,
        )
        if resp.status_code in {401, 403}:
            return ConnectorResult(
                notes=["OpenCorporates recusou (limite ou token). Sem OPENCORPORATES_API_TOKEN a API pública costuma falhar."]
            )
        if resp.status_code == 429:
            return ConnectorResult(notes=["OpenCorporates: rate limit. Tente de novo em instantes."])
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"OpenCorporates HTTP {resp.status_code}"])
        data = resp.json()
        results = (((data or {}).get("results") or {}).get("companies")) or []
        parsed = parse_opencorporates(results, origin_key=entity.canonical_key)
        if not parsed.entities:
            parsed.notes.append("OpenCorporates sem empresa pública para este nome.")
        return parsed
