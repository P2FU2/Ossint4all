"""Helpers de schema Judit."""

from __future__ import annotations

from typing import Any


def extract_request_id(payload: dict[str, Any]) -> str | None:
    for key in ("request_id", "requestId", "id"):
        if payload.get(key):
            return str(payload[key])
    data = payload.get("data") or {}
    if isinstance(data, dict):
        for key in ("request_id", "requestId", "id"):
            if data.get(key):
                return str(data[key])
    return None


def extract_response_type(payload: dict[str, Any]) -> str:
    for key in ("response_type", "responseType", "type", "event_type", "eventType"):
        if payload.get(key):
            return str(payload[key])
    return "unknown"


def extract_cached_flag(payload: dict[str, Any]) -> bool | None:
    if "cached_response" in payload:
        return bool(payload["cached_response"])
    if "cachedResponse" in payload:
        return bool(payload["cachedResponse"])
    return None


def extract_delivery_id(payload: dict[str, Any], headers: dict[str, str]) -> str | None:
    for key in ("delivery_id", "deliveryId", "webhook_id", "webhookId"):
        if payload.get(key):
            return str(payload[key])
    hdr = {k.lower(): v for k, v in headers.items()}
    for key in ("x-delivery-id", "x-webhook-id", "x-request-id"):
        if hdr.get(key):
            return hdr[key]
    return None
