"""PNCP — contratos e licitações públicas, sem chave."""

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


def _cnpj_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        return digits if validate_cnpj(digits) else None
    for ident in entity.identifiers or []:
        if ident.kind == "CNPJ" and validate_cnpj(ident.value):
            return only_digits(ident.value)
    return None


def _query_from_entity(entity: Entity) -> str | None:
    cnpj = _cnpj_from_entity(entity)
    if cnpj:
        return cnpj
    name = (entity.display_name or "").strip()
    if entity.entity_type in {"PERSON", "ORG"} and len(name) >= 5:
        return name
    return None


def _row_title(row: dict[str, Any]) -> str:
    return str(
        row.get("title")
        or row.get("titulo")
        or row.get("descricao")
        or row.get("objeto")
        or row.get("numeroControlePNCP")
        or row.get("numero_controle_pncp")
        or ""
    ).strip()


def _row_url(row: dict[str, Any]) -> str:
    url = str(row.get("item_url") or row.get("url") or row.get("link") or "").strip()
    if url.startswith("http"):
        return url
    controle = str(row.get("numeroControlePNCP") or row.get("numero_controle_pncp") or "").strip()
    if controle:
        return f"https://pncp.gov.br/app/contratos/{controle}"
    return "https://pncp.gov.br/"


def parse_pncp_items(rows: list[Any], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _row_title(row)
        if not title:
            continue
        orgao = str(row.get("orgao_nome") or row.get("organization_name") or row.get("nomeOrgao") or row.get("orgao") or "").strip()
        orgao_cnpj = only_digits(str(row.get("orgao_cnpj") or row.get("organization_cnpj") or row.get("cnpjOrgao") or row.get("cnpj") or ""))
        valor = row.get("valor_global") or row.get("valorGlobal") or row.get("valor") or row.get("valor_total")
        quando = str(row.get("data") or row.get("publication_date") or row.get("dataPublicacaoPncp") or row.get("dataVigenciaInicio") or "")
        url = _row_url(row)
        found = FoundEntity(
            entity_type="PUBLICATION",
            kind="URL",
            value=url,
            display_name=title[:180],
            attrs={
                "tipo": "contrato",
                "orgao": orgao,
                "valor": valor,
                "quando": quando,
                "fonte": "pncp",
            },
            confidence=0.62,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(
            FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="CONTRATO", confidence=0.6, attrs={"fonte": "pncp"})
        )
        if validate_cnpj(orgao_cnpj):
            buyer = FoundEntity(
                entity_type="ORG",
                kind="CNPJ",
                value=orgao_cnpj,
                display_name=orgao or orgao_cnpj,
                attrs={"tipo": "orgao_publico", "papel": "contratante"},
                confidence=0.7,
            )
            out.entities.append(buyer)
            buyer_key = canonical_key("CNPJ", orgao_cnpj)
            if buyer_key != origin_key:
                out.edges.append(
                    FoundEdge(
                        from_ref=origin_key,
                        to_ref=buyer_key,
                        rel_type="CONTRATO",
                        confidence=0.58,
                        attrs={"papel": "contratante", "titulo": title[:120]},
                    )
                )
        out.evidence.append(
            FoundEvidence(
                source_label="PNCP · contratações públicas",
                url=url,
                snippet=f"{title} · {orgao} {valor or ''}".strip()[:400],
                payload={"titulo": title, "orgao": orgao, "valor": valor, "quando": quando},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 16:
            break
    return out


class PncpPublicConnector:
    name = "pncp_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1 (pncp public)"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.pncp_public_enable, "via": "pncp.gov.br", "key": ""}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"} and _query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.pncp_public_enable:
            raise SkippedDisabled("PNCP desabilitado")
        query = _query_from_entity(entity)
        if not query:
            return ConnectorResult()
        try:
            resp = self.http.request(
                "GET",
                "https://pncp.gov.br/api/search/",
                params={"q": query, "ordenacao": "-data", "pagina": 0, "tam_pagina": 10, "status": "divulgada"},
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult(notes=["PNCP indisponível nesta rodada"])
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"PNCP HTTP {resp.status_code}"])
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult(notes=["PNCP JSON inválido"])
        rows: list[Any] = []
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            for key in ("items", "content", "data", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    rows = value
                    break
        parsed = parse_pncp_items(rows, origin_key=entity.canonical_key)
        if not parsed.entities:
            parsed.notes.append("Nenhum contrato/edital PNCP com esse termo nesta rodada.")
        return parsed
