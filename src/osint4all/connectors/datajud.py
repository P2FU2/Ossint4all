"""Conector DataJud — capa e partes de processo pelo CNJ."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import FailedAuthentication, FailedSource, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.validators import normalize_cnj

# segmento.tribunal → alias da API pública DataJud
TRIBUNAL_ALIAS = {
    "3.00": "api_publica_stj",
    "4.01": "api_publica_trf1",
    "4.02": "api_publica_trf2",
    "4.03": "api_publica_trf3",
    "4.04": "api_publica_trf4",
    "4.05": "api_publica_trf5",
    "4.06": "api_publica_trf6",
    "5.01": "api_publica_trt1",
    "5.02": "api_publica_trt2",
    "5.03": "api_publica_trt3",
    "5.04": "api_publica_trt4",
    "5.15": "api_publica_trt15",
    "8.13": "api_publica_tjmg",
    "8.19": "api_publica_tjrj",
    "8.21": "api_publica_tjrs",
    "8.24": "api_publica_tjsc",
    "8.26": "api_publica_tjsp",
    "8.05": "api_publica_tjba",
    "8.06": "api_publica_tjce",
    "8.07": "api_publica_tjdft",
    "8.08": "api_publica_tjes",
    "8.09": "api_publica_tjgo",
    "8.16": "api_publica_tjpr",
    "8.17": "api_publica_tjpe",
    "8.23": "api_publica_tjro",
    "8.25": "api_publica_tjse",
}


def alias_for_cnj(numero: str) -> str | None:
    parts = normalize_cnj(numero)
    if not parts:
        return None
    if parts.segmento == "1":
        return None
    return TRIBUNAL_ALIAS.get(f"{parts.segmento}.{parts.tribunal}")


def parse_datajud_hit(hit: dict[str, Any], cnj_digits: str) -> ConnectorResult:
    result = ConnectorResult()
    formatted = _format_cnj(cnj_digits)
    case_key = canonical_key("CNJ", cnj_digits)
    tribunal = str(hit.get("tribunal") or "")
    classe = ""
    classe_obj = hit.get("classe")
    if isinstance(classe_obj, dict):
        classe = str(classe_obj.get("nome") or "")
    elif classe_obj:
        classe = str(classe_obj)
    assuntos = hit.get("assuntos") or []
    assunto = ""
    if assuntos and isinstance(assuntos[0], dict):
        assunto = str(assuntos[0].get("nome") or "")
    result.entities.append(
        FoundEntity(
            entity_type="CASE",
            kind="CNJ",
            value=cnj_digits,
            display_name=formatted,
            attrs={
                "tribunal": tribunal,
                "classe": classe,
                "assunto": assunto,
                "grau": hit.get("grau"),
                "data_ajuizamento": hit.get("dataAjuizamento"),
                "formato": (hit.get("formato") or {}).get("nome") if isinstance(hit.get("formato"), dict) else hit.get("formato"),
            },
            confidence=0.95,
        )
    )
    for parte in hit.get("poloAtivo") or hit.get("polo_ativo") or []:
        _add_party(result, parte, case_key, "PARTE", "ativo")
    for parte in hit.get("poloPassivo") or hit.get("polo_passivo") or []:
        _add_party(result, parte, case_key, "PARTE", "passivo")
    for movimento in (hit.get("movimentos") or [])[:8]:
        if not isinstance(movimento, dict):
            continue
        nome = movimento.get("nome") or (movimento.get("complementosTabelados") or "")
        data = movimento.get("dataHora") or movimento.get("data")
        result.evidence.append(
            FoundEvidence(
                source_label="DataJud / CNJ",
                url="https://www.cnj.jus.br/sistemas/datajud/",
                snippet=f"{data or ''} — {nome}".strip(" —"),
                payload={"movimento": nome, "data": data},
                entity_ref=case_key,
            )
        )
    if not result.evidence:
        result.evidence.append(
            FoundEvidence(
                source_label="DataJud / CNJ",
                url="https://www.cnj.jus.br/sistemas/datajud/",
                snippet=f"Capa {formatted} · {tribunal} · {classe}",
                payload={"tribunal": tribunal, "classe": classe},
                entity_ref=case_key,
            )
        )
    return result


def _add_party(
    result: ConnectorResult,
    parte: Any,
    case_key: str,
    rel: str,
    polo: str,
) -> None:
    if isinstance(parte, str):
        nome = parte.strip()
        if not nome:
            return
        person = FoundEntity(entity_type="PERSON", kind="NAME", value=nome, display_name=nome, confidence=0.5)
        result.entities.append(person)
        result.edges.append(
            FoundEdge(
                from_ref=canonical_key("NAME", nome),
                to_ref=case_key,
                rel_type=rel,
                confidence=0.5,
                attrs={"polo": polo},
            )
        )
        return
    if not isinstance(parte, dict):
        return
    nome = str(parte.get("nome") or parte.get("nomePolo") or "").strip()
    if not nome:
        pessoa = parte.get("pessoa")
        if isinstance(pessoa, dict):
            nome = str(pessoa.get("nome") or "").strip()
    if not nome:
        return
    person = FoundEntity(entity_type="PERSON", kind="NAME", value=nome, display_name=nome, confidence=0.55)
    result.entities.append(person)
    result.edges.append(
        FoundEdge(
            from_ref=canonical_key("NAME", nome),
            to_ref=case_key,
            rel_type=rel,
            confidence=0.55,
            attrs={"polo": polo},
        )
    )
    advogados = parte.get("advogados") or []
    for adv in advogados:
        if not isinstance(adv, dict):
            continue
        anome = str(adv.get("nome") or "").strip()
        if not anome:
            continue
        result.entities.append(
            FoundEntity(entity_type="PERSON", kind="NAME", value=anome, display_name=anome, confidence=0.5)
        )
        result.edges.append(
            FoundEdge(
                from_ref=canonical_key("NAME", anome),
                to_ref=case_key,
                rel_type="ADVOGADO",
                confidence=0.5,
            )
        )


def _format_cnj(digits: str) -> str:
    parts = normalize_cnj(digits)
    return parts.numero_formatado if parts else digits


def _cnj_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("cnj:"):
        return entity.canonical_key.split(":", 1)[1]
    for ident in entity.identifiers:
        if ident.kind == "CNJ":
            parts = normalize_cnj(ident.value)
            if parts:
                return parts.numero_digits
    return None


class DatajudConnector:
    name = "datajud"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=settings.datajud_max_concurrency,
            timeout=30.0,
            default_headers={
                "Authorization": f"APIKey {settings.datajud_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "osint4all/0.1",
            },
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.datajud_enable,
            "api_key_configured": bool(self.settings.datajud_api_key),
            "api_key_url": self.settings.datajud_api_key_url,
        }

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type == "CASE" and _cnj_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.datajud_enable:
            raise SkippedDisabled("DataJud desabilitado")
        if not self.settings.datajud_api_key:
            raise FailedAuthentication(
                f"DATAJUD_API_KEY ausente. Chave pública: {self.settings.datajud_api_key_url}"
            )
        cnj = _cnj_from_entity(entity)
        if not cnj:
            return ConnectorResult()
        alias = alias_for_cnj(cnj)
        if not alias:
            return ConnectorResult(notes=["Tribunal sem endpoint DataJud (ex.: STF) ou alias desconhecido"])
        url = f"{self.settings.datajud_base_url.rstrip('/')}/{alias}/_search"
        body = {"size": 5, "query": {"match": {"numeroProcesso": cnj}}}
        resp = self.http.request("POST", url, json=body)
        if resp.status_code >= 400:
            raise FailedSource(f"DataJud HTTP {resp.status_code}")
        data = resp.json()
        hits = (((data or {}).get("hits") or {}).get("hits")) or []
        merged = ConnectorResult()
        for h in hits:
            src = h.get("_source") if isinstance(h, dict) else None
            if isinstance(src, dict):
                merged.merge(parse_datajud_hit(src, cnj))
        return merged
