"""Busca pública de empresas pelo nome do sócio (base aberta da Receita)."""

from __future__ import annotations

import re
from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import socio_doc_matches_cpf, validate_cnpj, validate_cpf

_CNPJ_RE = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")


def cpf_from_entity(entity: Entity) -> str | None:
    if str(getattr(entity, "canonical_key", "")).startswith("cpf:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        return digits if validate_cpf(digits) else None
    for ident in getattr(entity, "identifiers", None) or []:
        if ident.kind == "CPF":
            digits = only_digits(ident.value)
            if validate_cpf(digits):
                return digits
    return None


def name_query_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("name:"):
        name = (entity.display_name or "").strip()
        return name if " " in name else None
    if entity.entity_type == "PERSON" and " " in (entity.display_name or ""):
        return entity.display_name.strip()
    if entity.entity_type == "ORG" and not entity.canonical_key.startswith("cnpj:"):
        name = (entity.display_name or "").strip()
        return name or None
    return None


def extract_cnpjs(text: str) -> list[str]:
    found: list[str] = []
    for match in _CNPJ_RE.finditer(text or ""):
        digits = only_digits(match.group(1))
        if validate_cnpj(digits) and digits not in found:
            found.append(digits)
    return found


def _walk_cnpj_rows(blob: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(blob, list):
        for item in blob:
            rows.extend(_walk_cnpj_rows(item))
        return rows
    if not isinstance(blob, dict):
        return rows
    cnpj = only_digits(str(blob.get("cnpj") or blob.get("cnpj_cpf") or blob.get("taxId") or ""))
    if validate_cnpj(cnpj):
        rows.append(blob)
    for key in ("results", "data", "empresas", "cnpjs", "items", "rows"):
        if key in blob:
            rows.extend(_walk_cnpj_rows(blob[key]))
    return rows


def parse_socio_hits(
    rows: list[dict[str, Any]],
    *,
    origin_key: str,
    source_label: str,
    source_url: str | None = None,
    rel_type: str = "SOCIO",
    unconfirmed: bool = False,
) -> ConnectorResult:
    out = ConnectorResult()
    seen: set[str] = set()
    for row in rows:
        cnpj = only_digits(str(row.get("cnpj") or row.get("cnpj_cpf") or row.get("taxId") or ""))
        if not validate_cnpj(cnpj) or cnpj in seen:
            continue
        seen.add(cnpj)
        razao = str(
            row.get("razao_social")
            or row.get("razaoSocial")
            or row.get("nome")
            or row.get("company")
            or cnpj
        )
        fantasia = str(row.get("nome_fantasia") or row.get("nomeFantasia") or row.get("alias") or "")
        situacao = str(
            row.get("situacao_cadastral")
            or row.get("situacaoCadastral")
            or row.get("descricao_situacao_cadastral")
            or row.get("situacao")
            or ""
        )
        municipio = str(row.get("municipio") or row.get("cidade") or "")
        uf = str(row.get("uf") or row.get("estado") or "")
        cnae = str(row.get("cnae_fiscal_descricao") or row.get("cnae") or row.get("atividade_principal") or "")
        org_key = canonical_key("CNPJ", cnpj)
        out.entities.append(
            FoundEntity(
                entity_type="ORG",
                kind="CNPJ",
                value=cnpj,
                display_name=fantasia or razao,
                attrs={
                    "razao_social": razao,
                    "nome_fantasia": fantasia,
                    "situacao": situacao,
                    "municipio": municipio,
                    "uf": uf,
                    "cnae": cnae,
                    "from_socio_search": True,
                    "status": "unconfirmed" if unconfirmed else "confirmed",
                },
                confidence=0.45 if unconfirmed else 0.75,
            )
        )
        out.edges.append(
            FoundEdge(
                from_ref=origin_key,
                to_ref=org_key,
                rel_type=rel_type,
                confidence=0.45 if unconfirmed else 0.7,
                attrs={"fonte": source_label, "status": "unconfirmed" if unconfirmed else "confirmed"},
            )
        )
        bits = [razao, cnpj]
        if municipio or uf:
            bits.append(f"{municipio}/{uf}".strip("/"))
        if situacao:
            bits.append(situacao)
        out.evidence.append(
            FoundEvidence(
                source_label=source_label,
                url=source_url or f"https://minhareceita.org/{cnpj}",
                snippet=" · ".join(bit for bit in bits if bit),
                payload={"cnpj": cnpj, "razao_social": razao, "situacao": situacao},
                entity_ref=org_key,
            )
        )
    if seen:
        out.notes.append(f"{len(seen)} empresa(s) no quadro societário público")
    return out


class SocioSearchConnector:
    name = "socio_search"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1 (investigative journalism)"},
        )

    def collect_by_cpf(self, cpf: str, origin_key: str) -> ConnectorResult:
        """Empresas do QSA ligadas a este CPF. Sem chute: a API pública da Casa dos Dados não filtra CPF."""
        digits = only_digits(cpf)
        if not validate_cpf(digits):
            return ConnectorResult()
        if not self.settings.brasil_io_api_token:
            return ConnectorResult(
                notes=["Índice oficial de sócios por CPF (Brasil.IO) não está configurado. Não atribuímos empresas a este documento."]
            )
        return self._brasil_io_cpf(digits, origin_key)

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.socio_search_enable,
            "brasil_io": bool(self.settings.brasil_io_api_token),
        }

    def accepts(self, entity: Entity) -> bool:
        return cpf_from_entity(entity) is not None or name_query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.socio_search_enable:
            raise SkippedDisabled("busca de sócio desabilitada")
        cpf = cpf_from_entity(entity)
        name = name_query_from_entity(entity)
        if not cpf and not name:
            return ConnectorResult()
        origin = entity.canonical_key
        result = ConnectorResult()
        if cpf:
            result.merge(self.collect_by_cpf(cpf, origin))
            return result
        result.merge(self._casadosdados(name, origin, name_only=True))
        if self.settings.brasil_io_api_token:
            result.merge(self._brasil_io(name, origin, name_only=True))
        if not result.entities:
            result.merge(self._web_mentions(name, origin, ctx, name_only=True))
        return result

    def _hit_flags(self, name_only: bool) -> dict[str, Any]:
        return {"rel_type": "CANDIDATO" if name_only else "SOCIO", "unconfirmed": name_only}

    def _casadosdados(self, name: str, origin: str, *, name_only: bool = True) -> ConnectorResult:
        payload = {
            "busca_textual": [
                {
                    "texto": [name],
                    "tipo_busca": "exata",
                    "razao_social": False,
                    "nome_fantasia": False,
                    "nome_socio": True,
                }
            ],
            "limite": 20,
            "pagina": 1,
        }
        try:
            resp = self.http.request(
                "POST",
                "https://api.casadosdados.com.br/v5/public/cnpj/pesquisa",
                json=payload,
            )
        except Exception:
            return ConnectorResult(notes=["Casa dos Dados indisponível"])
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"Casa dos Dados HTTP {resp.status_code}"])
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        rows = _walk_cnpj_rows(data)
        return parse_socio_hits(
            rows,
            origin_key=origin,
            source_label="Receita Federal (índice público Casa dos Dados)",
            source_url="https://casadosdados.com.br/",
            **self._hit_flags(name_only),
        )

    def _brasil_io_cpf(self, digits: str, origin: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://api.brasil.io/v1/dataset/socios-brasil/socios/data/",
                headers={"Authorization": f"Token {self.settings.brasil_io_api_token}"},
                params={"cnpj_cpf_do_socio": digits, "page_size": 20},
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"Brasil.IO HTTP {resp.status_code}"])
        data = resp.json()
        rows = data.get("results") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            rows = []
        matched = [
            row
            for row in rows
            if isinstance(row, dict)
            and socio_doc_matches_cpf(str(row.get("cnpj_cpf_do_socio") or row.get("cpf") or ""), digits)
        ]
        return parse_socio_hits(
            matched,
            origin_key=origin,
            source_label="Receita Federal (Brasil.IO / sócios · CPF)",
            source_url="https://brasil.io/dataset/socios-brasil/socios/",
        )

    def _brasil_io(self, name: str, origin: str, *, name_only: bool = True) -> ConnectorResult:
        resp = self.http.request(
            "GET",
            "https://api.brasil.io/v1/dataset/socios-brasil/socios/data/",
            headers={"Authorization": f"Token {self.settings.brasil_io_api_token}"},
            params={"nome_socio": name.upper(), "page_size": 20},
        )
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"Brasil.IO HTTP {resp.status_code}"])
        data = resp.json()
        rows = data.get("results") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            rows = []
        return parse_socio_hits(
            rows,
            origin_key=origin,
            source_label="Receita Federal (Brasil.IO / dados abertos)",
            source_url="https://brasil.io/dataset/socios-brasil/socios/",
            **self._hit_flags(name_only),
        )

    def _web_mentions(self, name: str, origin: str, ctx: ExpandContext, *, name_only: bool = True) -> ConnectorResult:
        from osint4all.connectors.cnpj_receita import CnpjReceitaConnector, parse_cnpj_payload
        from osint4all.connectors.web_search import WebSearchConnector, web_search_ready
        from osint4all.graph.identity import names_match

        search = WebSearchConnector(self.settings)
        if not web_search_ready(self.settings):
            return ConnectorResult(notes=["Configure SearXNG, busca web ou BRASIL_IO_API_TOKEN para achar empresas pelo nome"])
        query = f'"{name}" (sócio OR CNPJ OR "quadro societário")'
        try:
            hits = search.search(query, origin)
        except Exception:
            return ConnectorResult(notes=["Busca web não retornou menções."])
        blob = " ".join(f"{ev.snippet or ''} {ev.url or ''}" for ev in hits.evidence)
        verified: list[dict[str, Any]] = []
        receita = CnpjReceitaConnector(self.settings)
        for cnpj in extract_cnpjs(blob)[:8]:
            try:
                parsed = parse_cnpj_payload(receita._fetch(cnpj))
            except Exception:
                continue
            if any(e.entity_type == "PERSON" and names_match(e.display_name, name) for e in parsed.entities):
                org = next((e for e in parsed.entities if e.kind == "CNPJ"), None)
                verified.append({"cnpj": cnpj, "razao_social": (org.display_name if org else cnpj)})
        if not verified:
            return ConnectorResult(notes=["Menções web sem QSA que confirme o nome. Nada foi ligado."])
        out = parse_socio_hits(
            verified,
            origin_key=origin,
            source_label="Menção pública + QSA oficial",
            **self._hit_flags(name_only),
        )
        out.merge(hits)
        return out
