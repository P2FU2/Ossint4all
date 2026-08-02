"""Parse e chaves de idempotência de webhooks Judit."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from monitor_jus import NORMALIZER_VERSION, PROVIDER_SCHEMA_VERSION_JUDIT
from monitor_jus.sources.judit.schemas import (
    extract_cached_flag,
    extract_delivery_id,
    extract_request_id,
    extract_response_type,
)


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_delivery_key(payload: dict[str, Any], headers: dict[str, str]) -> str:
    delivery_id = extract_delivery_id(payload, headers)
    if delivery_id:
        return hashlib.sha256(f"judit|{delivery_id}".encode()).hexdigest()
    request_id = extract_request_id(payload) or ""
    response_type = extract_response_type(payload)
    cached = extract_cached_flag(payload)
    cached_s = "" if cached is None else str(cached).lower()
    ph = payload_hash(payload)
    basis = f"{request_id}|{response_type}|{cached_s}|{ph}"
    return hashlib.sha256(basis.encode()).hexdigest()


def classify_webhook_event_type(payload: dict[str, Any]) -> str:
    """Mapeia tipo bruto Judit -> EventType string (ou unknown)."""
    rtype = extract_response_type(payload).lower()
    text_blob = json.dumps(payload, ensure_ascii=False).lower()
    if "djen" in rtype or "diario" in rtype or "diário" in text_blob or "djen" in text_blob:
        return "PUBLICACAO_DJEN"
    if "intim" in rtype or "intim" in text_blob:
        return "INTIMACAO_PROCESSUAL"
    if "lawsuit" in rtype or "process" in rtype or "novo_processo" in rtype:
        if "step" in rtype or "movement" in rtype or "movimento" in rtype:
            return "MOVIMENTACAO_PROCESSUAL"
        return "PROCESSO_DESCOBERTO"
    if "step" in rtype or "movement" in rtype or "movimento" in rtype:
        return "MOVIMENTACAO_PROCESSUAL"
    if "communication" in rtype or "publicacao" in rtype:
        return "COMUNICACAO_OUTRA"
    return "UNKNOWN"


def webhook_meta(payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    return {
        "delivery_key": build_delivery_key(payload, headers),
        "request_id": extract_request_id(payload),
        "response_type": extract_response_type(payload),
        "cached_response": extract_cached_flag(payload),
        "payload_hash": payload_hash(payload),
        "provider_schema_version": PROVIDER_SCHEMA_VERSION_JUDIT,
        "normalizer_version": NORMALIZER_VERSION,
        "webhook_delivery_id": extract_delivery_id(payload, headers),
        "classified_type": classify_webhook_event_type(payload),
    }
