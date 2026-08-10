"""Chaves de identidade de eventos / movimentos."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


def _norm(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _dt(value: datetime | str | None) -> str:
    """Normaliza data para comparação estável (UTC, sem microssegundos/offset)."""
    if value is None:
        return ""
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def sha256_hex(*parts: str) -> str:
    basis = "|".join(parts)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def movement_key(
    *,
    source_name: str,
    source_event_id: str | None,
    numero_cnj: str,
    codigo_movimento_tpu: str | None,
    data_hora: datetime | str | None,
    complemento: str | None,
    orgao_julgador: str | None,
    sequencia_origem: str | None = None,
) -> str:
    if source_event_id:
        return sha256_hex(source_name, "src", source_event_id)
    return sha256_hex(
        source_name,
        source_event_id or "",
        numero_cnj,
        codigo_movimento_tpu or "",
        _dt(data_hora),
        _norm(complemento),
        _norm(orgao_julgador),
        sequencia_origem or "",
    )


def material_movement_tuple(
    *,
    movement_code: str | None,
    data_hora: datetime | str | None,
    description: str | None,
    orgao: str | None,
    complemento: str | None,
) -> tuple[str, str, str, str, str]:
    """Representação material da última movimentação (não fingerprint bruto)."""
    return (
        str(movement_code or "").strip(),
        _dt(data_hora),
        _norm(description),
        _norm(orgao),
        _norm(complemento),
    )


def material_movement_from_mapping(data: dict[str, Any] | None) -> tuple[str, str, str, str, str]:
    data = data or {}
    return material_movement_tuple(
        movement_code=str(data.get("movement_code") or data.get("codigo") or "") or None,
        data_hora=data.get("datetime") or data.get("data_hora") or data.get("last_movement_date"),
        description=str(data.get("description") or data.get("nome") or data.get("last_movement_name") or "")
        or None,
        orgao=str(data.get("orgao") or data.get("orgao_julgador") or "") or None,
        complemento=str(data.get("complemento") or "") or None,
    )


def movement_identity_hash(
    *,
    numero_cnj: str,
    movement_code: str | None,
    data_hora: datetime | str | None,
    description: str | None,
    orgao: str | None,
    complemento: str | None,
) -> str:
    return sha256_hex(
        "MOVIMENTACAO_PROCESSUAL",
        "datajud",
        numero_cnj,
        *material_movement_tuple(
            movement_code=movement_code,
            data_hora=data_hora,
            description=description,
            orgao=orgao,
            complemento=complemento,
        ),
    )


def communication_key(
    *,
    source_name: str,
    source_event_id: str | None,
    communication_type: str,
    numero_cnj: str | None,
    published_at: datetime | str | None,
    body: str | None,
) -> str:
    if source_event_id:
        return sha256_hex(source_name, "comm", source_event_id)
    return sha256_hex(
        source_name,
        communication_type,
        numero_cnj or "",
        _dt(published_at),
        _norm(body)[:500],
    )


def extract_cnj_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("numero_cnj", "numeroProcesso", "cnj", "lawsuit_cnj", "code"):
        if payload.get(key):
            return str(payload[key])
    data = payload.get("data") or payload.get("lawsuit") or {}
    if isinstance(data, dict):
        for key in ("numero_cnj", "numeroProcesso", "cnj", "code"):
            if data.get(key):
                return str(data[key])
        response = data.get("response_data") or data.get("response") or {}
        if isinstance(response, dict):
            for key in ("codigo_processo", "numero_cnj", "code", "cnj"):
                if response.get(key):
                    return str(response[key])
    return None
