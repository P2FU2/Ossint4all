"""Normalização de payloads Judit / DataJud."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from monitor_jus import NORMALIZER_VERSION, PROVIDER_SCHEMA_VERSION_JUDIT
from monitor_jus.models import EventType, NormalizedEvent
from monitor_jus.pipeline.identity import (
    communication_key,
    extract_cnj_from_payload,
    movement_key,
)
from monitor_jus.sources.judit.webhooks import payload_hash
from monitor_jus.validators import normalize_cnj


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


def normalize_judit_webhook(
    payload: dict[str, Any],
    classified_type: str,
) -> NormalizedEvent | None:
    if classified_type == "UNKNOWN":
        return None

    event_type = EventType(classified_type)
    cnj_raw = extract_cnj_from_payload(payload)
    parts = normalize_cnj(cnj_raw) if cnj_raw else None
    numero = parts.numero_formatado if parts else cnj_raw

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    lawsuit = data.get("lawsuit") if isinstance(data, dict) else None
    if not isinstance(lawsuit, dict):
        lawsuit = data if isinstance(data, dict) else {}

    source_event_id = None
    for key in ("id", "event_id", "step_id", "publication_id"):
        if payload.get(key):
            source_event_id = str(payload[key])
            break
        if isinstance(data, dict) and data.get(key):
            source_event_id = str(data[key])
            break

    steps = lawsuit.get("steps") or lawsuit.get("movements") or []
    last_step = steps[-1] if isinstance(steps, list) and steps else {}
    if not isinstance(last_step, dict):
        last_step = {}

    codigo = str(last_step.get("codigo") or last_step.get("code") or "") or None
    nome = str(
        last_step.get("nome")
        or last_step.get("name")
        or payload.get("title")
        or classified_type
    )
    data_hora = _parse_dt(
        last_step.get("dataHora")
        or last_step.get("date")
        or payload.get("published_at")
        or payload.get("created_at")
    )
    orgao = str(
        lawsuit.get("orgao_julgador")
        or (lawsuit.get("court") or {}).get("name")
        if isinstance(lawsuit.get("court"), dict)
        else lawsuit.get("court")
        or ""
    ) or None
    complemento = str(last_step.get("complemento") or last_step.get("content") or "") or None
    sequencia = str(last_step.get("sequencia") or last_step.get("sequence") or "") or None

    if event_type in (
        EventType.PUBLICACAO_DJEN,
        EventType.INTIMACAO_PROCESSUAL,
        EventType.COMUNICACAO_OUTRA,
    ):
        body = str(payload.get("content") or payload.get("text") or complemento or nome)
        identity = communication_key(
            source_name="judit",
            source_event_id=source_event_id,
            communication_type=event_type.value,
            numero_cnj=numero,
            published_at=data_hora,
            body=body,
        )
        description = body
    else:
        identity = movement_key(
            source_name="judit",
            source_event_id=source_event_id,
            numero_cnj=numero or "",
            codigo_movimento_tpu=codigo,
            data_hora=data_hora,
            complemento=complemento,
            orgao_julgador=orgao,
            sequencia_origem=sequencia,
        )
        description = complemento or nome

    ph = payload_hash(payload)
    tribunal = None
    if isinstance(lawsuit.get("tribunal"), str):
        tribunal = lawsuit.get("tribunal")
    elif isinstance(lawsuit.get("court"), dict):
        tribunal = lawsuit["court"].get("code") or lawsuit["court"].get("name")

    return NormalizedEvent(
        event_type=event_type,
        event_identity_key=identity,
        source_name="judit",
        source_event_id=source_event_id,
        numero_cnj=numero,
        tribunal=tribunal,
        title=nome,
        description=description or "",
        movement_code=codigo,
        movement_date=data_hora,
        orgao_julgador=orgao,
        complemento=complemento,
        sequencia_origem=sequencia,
        payload=payload,
        payload_hash=ph,
        cached_response=payload.get("cached_response"),
        provider_schema_version=PROVIDER_SCHEMA_VERSION_JUDIT,
        normalizer_version=NORMALIZER_VERSION,
        official_link=lawsuit.get("url") if isinstance(lawsuit, dict) else None,
    )


def normalize_datajud_source(source: dict[str, Any]) -> dict[str, Any]:
    """Extrai campos úteis do _source DataJud."""
    movimentos = source.get("movimentos") or []
    last = movimentos[-1] if movimentos else {}
    assuntos = source.get("assuntos") or []
    assunto_principal = None
    if assuntos:
        principal = next((a for a in assuntos if a.get("principal")), assuntos[0])
        assunto_principal = principal.get("nome")
    return {
        "numero_cnj_digits": source.get("numeroProcesso"),
        "tribunal": source.get("tribunal"),
        "classe": (source.get("classe") or {}).get("nome"),
        "assunto": assunto_principal,
        "orgao_julgador": (source.get("orgaoJulgador") or {}).get("nome"),
        "grau": source.get("grau"),
        "data_ajuizamento": source.get("dataAjuizamento"),
        "last_movement_name": last.get("nome"),
        "last_movement_date": last.get("dataHora"),
        "movimentos": movimentos,
        "raw": source,
    }
