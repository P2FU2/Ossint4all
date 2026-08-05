"""Normalização de payloads DataJud / DJEN."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from monitor_jus import NORMALIZER_VERSION
from monitor_jus.official_portal import resolve_official_link
from monitor_jus.validators import normalize_cnj


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


def normalize_datajud_source(source: dict[str, Any]) -> dict[str, Any]:
    """Extrai campos úteis do _source DataJud."""
    # Aceita wrapper ES hits ou _source direto
    if "hits" in source and isinstance(source.get("hits"), dict):
        hits = source["hits"].get("hits") or []
        if hits and isinstance(hits[0], dict):
            source = hits[0].get("_source") or source
    elif "_source" in source and isinstance(source.get("_source"), dict):
        source = source["_source"]

    movimentos = source.get("movimentos") or []
    last = movimentos[-1] if movimentos else {}
    assuntos = source.get("assuntos") or []
    assunto_principal = None
    if assuntos:
        principal = next((a for a in assuntos if a.get("principal")), assuntos[0])
        assunto_principal = principal.get("nome")

    last_movement_at = _parse_dt(last.get("dataHora") if isinstance(last, dict) else None)

    return {
        "numero_cnj_digits": source.get("numeroProcesso"),
        "tribunal": source.get("tribunal"),
        "classe": (source.get("classe") or {}).get("nome")
        if isinstance(source.get("classe"), dict)
        else source.get("classe"),
        "assunto": assunto_principal,
        "orgao_julgador": (source.get("orgaoJulgador") or {}).get("nome")
        if isinstance(source.get("orgaoJulgador"), dict)
        else source.get("orgaoJulgador"),
        "grau": source.get("grau"),
        "data_ajuizamento": source.get("dataAjuizamento"),
        "last_movement_name": last.get("nome") if isinstance(last, dict) else None,
        "last_movement_date": last.get("dataHora") if isinstance(last, dict) else None,
        "last_movement_at": last_movement_at,
        "movimentos": movimentos,
        "raw": source,
        "normalizer_version": NORMALIZER_VERSION,
        "official_link": resolve_official_link(
            None,
            tribunal=str(source.get("tribunal") or "") or None,
            payload=source,
        ),
    }
