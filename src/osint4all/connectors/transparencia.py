"""Conector Portal da Transparência (CEIS / CNEP / CNPJ)."""

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


TRANSPARENCIA_LISTAS = (
    ("CEIS", "ceis", "codigoSancionado"),
    ("CNEP", "cnep", "codigoSancionado"),
    ("CEAF", "ceaf", "cpfSancionado"),
    ("CEPIM", "cepim", "cnpjSancionado"),
    ("PEP", "pep", "cpf"),
)


def transparencia_params(lista: str, codigo: str) -> dict[str, Any] | None:
    """CEAF e CEPIM não aceitam codigoSancionado — cada lista tem o próprio campo."""
    digits = only_digits(codigo)
    if not digits:
        return None
    key = (lista or "").upper()
    if key in {"CEIS", "CNEP"}:
        return {"codigoSancionado": digits, "pagina": 1}
    if key == "CEAF":
        return {"cpfSancionado": digits, "pagina": 1} if len(digits) == 11 else None
    if key == "CEPIM":
        return {"cnpjSancionado": digits, "pagina": 1} if len(digits) == 14 else None
    if key == "PEP":
        return {"cpf": digits, "pagina": 1} if len(digits) == 11 else None
    return None


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
            "free_fallback": True,
            "via": "portal scrape" if not self.settings.transparencia_api_key else "api + portal",
        }

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"}

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.transparencia_enable:
            raise SkippedDisabled("Transparência desabilitada")
        codigo = None
        for ident in entity.identifiers:
            if ident.kind in {"CPF", "CNPJ"}:
                codigo = only_digits(ident.value)
                break
        if entity.canonical_key.startswith(("cpf:", "cnpj:")):
            codigo = entity.canonical_key.split(":", 1)[1]
        nome = (entity.display_name or "").strip()
        merged = ConnectorResult()
        if self.settings.transparencia_api_key and codigo:
            merged.merge(self._api_listas(codigo, entity.canonical_key))
        if not merged.entities:
            merged.merge(self._portal_scrape(entity.canonical_key, codigo=codigo or "", nome=nome))
        if not merged.entities and not merged.evidence:
            merged.notes.append("Nenhum registro público CEIS/CNEP/CEAF/CEPIM/PEP para este alvo.")
        return merged

    def _api_listas(self, codigo: str, origin_key: str) -> ConnectorResult:
        merged = ConnectorResult()
        for lista, path, _field in TRANSPARENCIA_LISTAS:
            params = transparencia_params(lista, codigo)
            if not params:
                continue
            resp, err = self.http.safe_request(
                "GET",
                f"https://api.portaldatransparencia.gov.br/api-de-dados/{path}",
                params=params,
                max_retries=1,
            )
            if err or resp is None:
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            rows = data if isinstance(data, list) else data.get("data") or []
            merged.merge(parse_transparencia_rows(rows if isinstance(rows, list) else [], origin_key=origin_key, lista=lista))
        return merged

    def _portal_scrape(self, origin_key: str, *, codigo: str, nome: str) -> ConnectorResult:
        from osint4all.connectors.html_public import parse_portal_html, parse_portal_payload

        merged = ConnectorResult()
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://portaldatransparencia.gov.br/sancoes/consulta",
        }
        consultas = []
        if codigo:
            consultas.extend(
                (
                    ("CEIS", "https://portaldatransparencia.gov.br/sancoes/consulta/resultado", {"cadastro": 1, "cpfCnpj": codigo}),
                    ("CNEP", "https://portaldatransparencia.gov.br/sancoes/consulta/resultado", {"cadastro": 2, "cpfCnpj": codigo}),
                    ("CEAF", "https://portaldatransparencia.gov.br/sancoes/consulta/resultado", {"cadastro": 3, "cpfCnpj": codigo}),
                    ("CEPIM", "https://portaldatransparencia.gov.br/sancoes/consulta/resultado", {"cadastro": 4, "cpfCnpj": codigo}),
                )
            )
        if nome and len(nome.split()) >= 2:
            consultas.append(
                (
                    "PEP",
                    "https://portaldatransparencia.gov.br/pessoa-exposta-politicamente/consulta/resultado",
                    {"nome": nome},
                )
            )
            consultas.append(
                (
                    "CEIS",
                    "https://portaldatransparencia.gov.br/sancoes/consulta/resultado",
                    {"cadastro": 1, "nomeSancionado": nome},
                )
            )
        common = {"paginacaoSimples": "true", "tamanhoPagina": 15, "offset": 0, "direcaoOrdenacao": "asc"}
        for lista, url, extra in consultas:
            params = {**common, **extra}
            resp, err = self.http.safe_request("GET", url, params=params, headers=headers, max_retries=1)
            if err or resp is None:
                continue
            parsed = ConnectorResult()
            try:
                parsed = parse_portal_payload(resp.json(), origin_key=origin_key, lista=lista)
            except Exception:
                parsed = parse_portal_html(resp.text or "", origin_key=origin_key, lista=lista)
            merged.merge(parsed)
            if len(merged.entities) >= 12:
                break
        if not merged.entities:
            from urllib.parse import quote_plus

            termo = codigo or nome
            if termo:
                merged.evidence.append(
                    FoundEvidence(
                        source_label="Portal da Transparência · busca",
                        url=f"https://portaldatransparencia.gov.br/busca?termo={quote_plus(termo)}",
                        snippet=f"Consulta pública gratuita · {termo}",
                        payload={"termo": termo, "via": "scraper"},
                        entity_ref=origin_key,
                    )
                )
        return merged
