"""Normalização de payloads DataJud / DJEN."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from monitor_jus import NORMALIZER_VERSION
from monitor_jus.instances import (
    instance_from_cnj_court,
    instance_label,
    summarize_instances,
)
from monitor_jus.official_portal import resolve_official_link
from monitor_jus.pipeline.status_oficial import normalize_situacao_key, situacao_label
from monitor_jus.sources.datajud import grau_rank, prefer_datajud_hit

_JULGADO_RE = re.compile(
    r"\b(julgad[oa]|ac[oó]rd[aã]o|tr[aâ]nsito\s+em\s+julgado|julgamento)\b",
    re.IGNORECASE,
)
_RECURSO_RE = re.compile(
    r"(remetid[oa].*tribunal|grau\s+de\s+recurso|recurso|remessa.*tribunal|col[eé]gio\s+recursal)",
    re.IGNORECASE,
)
# Ordem: terminais primeiro (badge e-SAJ / modal cposg)
_SITUACAO_PRIORITY = (
    "cancelado",
    "extinto",
    "encerrado",
    "julgado",
    "baixado",
    "arquivado",
    "suspenso",
    "em_grau_de_recurso",
)


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _classe_nome(source: dict[str, Any]) -> str | None:
    classe = source.get("classe")
    if isinstance(classe, dict):
        return classe.get("nome")
    if isinstance(classe, str):
        return classe
    return None


def _orgao_nome(source: dict[str, Any]) -> str | None:
    orgao = source.get("orgaoJulgador")
    if isinstance(orgao, dict):
        return orgao.get("nome")
    if isinstance(orgao, str):
        return orgao
    return None


def _assunto_principal(source: dict[str, Any]) -> str | None:
    assuntos = source.get("assuntos") or []
    if not assuntos:
        return None
    principal = next((a for a in assuntos if isinstance(a, dict) and a.get("principal")), None)
    if principal:
        return principal.get("nome")
    first = assuntos[0]
    return first.get("nome") if isinstance(first, dict) else None


def _movimento_complemento(mov: dict[str, Any]) -> str | None:
    comps = mov.get("complementosTabelados") or mov.get("complementos") or []
    parts: list[str] = []
    if isinstance(comps, list):
        for item in comps:
            if isinstance(item, dict):
                val = item.get("nome") or item.get("descricao") or item.get("valor") or item.get("texto")
                if val:
                    parts.append(str(val))
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
    if mov.get("complemento"):
        parts.append(str(mov.get("complemento")))
    text = " ".join(parts).strip()
    return text or None


def _infer_situacao_from_hits(sources: list[dict[str, Any]]) -> str | None:
    """Infere status de capa a partir de G1/G2 e movimentos.

    Cobre badges e-SAJ (Cancelado, Suspenso) e modal cposg ("2º Grau Encerrado").
    """
    if not sources:
        return None

    graus = {str(s.get("grau") or "").upper() for s in sources}
    has_g2 = any(grau_rank(g) >= 2 for g in graus)
    has_g1 = any(grau_rank(g) == 1 for g in graus)

    preferred = prefer_datajud_hit(sources)
    # Movimentos do mais recente ao mais antigo (preferido primeiro)
    ordered_movs: list[str] = []
    seen: set[str] = set()
    for src in [preferred, *sources]:
        for mov in reversed(src.get("movimentos") or []):
            if not isinstance(mov, dict) or not mov.get("nome"):
                continue
            nome = str(mov["nome"]).strip()
            if not nome or nome in seen:
                continue
            seen.add(nome)
            ordered_movs.append(nome)

    for nome in ordered_movs:
        key = normalize_situacao_key(nome)
        if key in _SITUACAO_PRIORITY:
            if key == "arquivado" and "definitiv" in nome.lower():
                return "Extinto"
            return situacao_label(key)

    joined = " | ".join(ordered_movs[:30])
    if _JULGADO_RE.search(joined):
        return "Julgado"

    # No e-SAJ, G2 com "Outras Decisões" / acórdão costuma aparecer como "Julgado"
    g2_sources = [s for s in sources if grau_rank(s.get("grau")) >= 2]
    for src in g2_sources or [preferred]:
        for mov in src.get("movimentos") or []:
            if not isinstance(mov, dict):
                continue
            nome = str(mov.get("nome") or "").lower()
            if "outras decis" in nome or "acórdão" in nome or "acordao" in nome:
                return "Julgado"

    if has_g2 and has_g1:
        # Duas capas: 1º grau = "Em grau de recurso"; sem julgamento explícito no G2
        return "Em grau de recurso"
    if has_g2:
        # Modal cposg frequentemente mostra "2º Grau Encerrado" sem movimento homônimo
        if re.search(r"\bencerrad", joined, re.IGNORECASE):
            return "Encerrado"
        return "Em tramitação"
    if has_g1 and _RECURSO_RE.search(joined):
        return "Em grau de recurso"
    return None


def normalize_datajud_source(source: dict[str, Any]) -> dict[str, Any]:
    """Extrai campos úteis de um único _source DataJud."""
    if "hits" in source and isinstance(source.get("hits"), dict):
        hits = source["hits"].get("hits") or []
        if hits and isinstance(hits[0], dict):
            source = hits[0].get("_source") or source
    elif "_source" in source and isinstance(source.get("_source"), dict):
        source = source["_source"]

    movimentos = source.get("movimentos") or []
    last = movimentos[-1] if movimentos else {}
    last_dict = last if isinstance(last, dict) else {}
    last_movement_at = _parse_dt(last_dict.get("dataHora"))

    return {
        "numero_cnj_digits": source.get("numeroProcesso"),
        "tribunal": source.get("tribunal"),
        "classe": _classe_nome(source),
        "assunto": _assunto_principal(source),
        "orgao_julgador": _orgao_nome(source),
        "grau": source.get("grau"),
        "data_ajuizamento": source.get("dataAjuizamento"),
        "last_movement_name": last_dict.get("nome"),
        "last_movement_date": last_dict.get("dataHora"),
        "last_movement_code": (
            last_dict.get("codigo")
            or last_dict.get("codigoNacional")
            or last_dict.get("codigoMovimento")
        ),
        "last_movement_complemento": _movimento_complemento(last_dict),
        "last_movement_at": last_movement_at,
        "movimentos": movimentos,
        "raw": source,
        "normalizer_version": NORMALIZER_VERSION,
        "official_link": resolve_official_link(
            None,
            tribunal=str(source.get("tribunal") or "") or None,
            payload=source,
            grau=str(source.get("grau") or "") or None,
            classe=_classe_nome(source),
        ),
    }


def normalize_datajud_hits(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Normaliza hits multi-instância e escolhe capa da mais alta conhecida.

    Mesmo CNJ: 1º e 2º grau (fundamentais). Superiores/STF costumam ter CNJ
    próprio e entram via process_relations; aqui classificamos quando o hit
    já apontar tribunal/segmento superior.
    """
    if not sources:
        return {}
    preferred = prefer_datajud_hit(sources)
    base = normalize_datajud_source(preferred)
    instances = []
    for src in sources:
        movs = src.get("movimentos") or []
        last = movs[-1] if movs else {}
        level = instance_from_cnj_court(
            src.get("numeroProcesso"),
            str(src.get("tribunal") or "") or None,
            grau=str(src.get("grau") or "") or None,
        )
        instances.append(
            {
                "grau": src.get("grau"),
                "tribunal": src.get("tribunal"),
                "process_number": src.get("numeroProcesso"),
                "instance_level": int(level),
                "instance_label": instance_label(level),
                "classe": _classe_nome(src),
                "orgao_julgador": _orgao_nome(src),
                "assunto": _assunto_principal(src),
                "last_movement_name": last.get("nome") if isinstance(last, dict) else None,
                "last_movement_at": last.get("dataHora") if isinstance(last, dict) else None,
            }
        )
    situacao = _infer_situacao_from_hits(sources)
    summary = summarize_instances(instances)
    active_level = instance_from_cnj_court(
        preferred.get("numeroProcesso"),
        str(preferred.get("tribunal") or "") or None,
        grau=str(preferred.get("grau") or "") or None,
    )
    base["situacao"] = situacao
    base["instances"] = instances
    base["instance_summary"] = summary
    base["instance_level"] = int(active_level)
    base["instance_label"] = instance_label(active_level)
    base["has_second_degree"] = any(grau_rank(s.get("grau")) >= 2 for s in sources)
    base["reached_superior"] = bool(summary.get("reached_superior"))
    base["all_sources"] = sources
    # Link: se há 2º grau no mesmo CNJ, forçar portal de 2ª instância
    if base.get("has_second_degree"):
        base["official_link"] = resolve_official_link(
            None,
            tribunal=str(preferred.get("tribunal") or "") or None,
            payload=preferred,
            grau="G2",
            classe=base.get("classe"),
        )
    return base
