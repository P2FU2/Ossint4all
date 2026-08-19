"""Conector Portal da Transparência (CEIS / CNEP / CNPJ)."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import FailedAuthentication, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj, validate_cpf


def parse_transparencia_rows(
    rows: list[dict[str, Any]],
    *,
    origin_key: str,
    lista: str,
) -> ConnectorResult:
    result = ConnectorResult()
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        nome = str(row.get("nome") or row.get("nomeSancionado") or row.get("razaoSocial") or "").strip()
        doc = only_digits(str(row.get("cpfCnpj") or row.get("cnpj") or row.get("cpf") or ""))
        orgao = str(row.get("orgao") or row.get("orgaoSancionador") or "")
        if validate_cnpj(doc):
            found = FoundEntity(entity_type="ORG", kind="CNPJ", value=doc, display_name=nome or doc, confidence=0.8)
            ref = canonical_key("CNPJ", doc)
        elif validate_cpf(doc):
            found = FoundEntity(entity_type="PERSON", kind="CPF", value=doc, display_name=nome or doc, confidence=0.8)
            ref = canonical_key("CPF", doc)
        elif nome:
            found = FoundEntity(entity_type="PERSON", kind="NAME", value=nome, display_name=nome, confidence=0.45)
            ref = canonical_key("NAME", nome)
        else:
            continue
        result.entities.append(found)
        if ref != origin_key:
            result.edges.append(
                FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.6, attrs={"lista": lista})
            )
        result.evidence.append(
            FoundEvidence(
                source_label=f"Portal da Transparência · {lista}",
                url="https://portaldatransparencia.gov.br/",
                snippet=f"{nome} {orgao}".strip(),
                payload=row,
                entity_ref=ref,
            )
        )
    return result


class TransparenciaConnector:
    name = "transparencia"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        headers = {"Accept": "application/json", "User-Agent": "osint4all/0.1"}
        if settings.transparencia_api_key:
            headers["chave-api-dados"] = settings.transparencia_api_key
        self.http = RateLimitedClient(source=self.name, max_concurrency=2, timeout=25.0, default_headers=headers)

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.transparencia_enable,
            "api_key_configured": bool(self.settings.transparencia_api_key),
        }

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"}

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.transparencia_enable:
            raise SkippedDisabled("Transparência desabilitada")
        if not self.settings.transparencia_api_key:
            raise FailedAuthentication(
                "TRANSPARENCIA_API_KEY ausente. Cadastre em https://api.portaldatransparencia.gov.br/"
            )
        codigo = None
        for ident in entity.identifiers:
            if ident.kind in {"CPF", "CNPJ"}:
                codigo = only_digits(ident.value)
                break
        if entity.canonical_key.startswith(("cpf:", "cnpj:")):
            codigo = entity.canonical_key.split(":", 1)[1]
        if not codigo:
            return ConnectorResult(notes=["Transparência exige CPF/CNPJ"])
        merged = ConnectorResult()
        for lista, path in (("CEIS", "ceis"), ("CNEP", "cnep")):
            url = f"https://api.portaldatransparencia.gov.br/api-de-dados/{path}"
            try:
                resp = self.http.request("GET", url, params={"codigoSancionado": codigo, "pagina": 1})
            except Exception:
                continue
            if resp.status_code >= 400:
                continue
            data = resp.json()
            rows = data if isinstance(data, list) else data.get("data") or []
            merged.merge(parse_transparencia_rows(rows, origin_key=entity.canonical_key, lista=lista))
        return merged
