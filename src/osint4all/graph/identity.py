"""Regras de identidade: nome não confirma pessoa; âncora forte ou QSA sim."""

from __future__ import annotations

import re
from typing import Any

from osint4all.connectors.base import FoundEntity
from osint4all.db.models import Entity
from osint4all.identifiers import canonical_key


def collapse_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def name_tokens(value: str) -> list[str]:
    return [token for token in collapse_name(value).split() if token]


def names_match(left: str, right: str) -> bool:
    a, b = collapse_name(left), collapse_name(right)
    return bool(a) and a == b


def is_weak_name(value: str) -> bool:
    return len(name_tokens(value)) < 3


def entity_status(obj: FoundEntity | Entity | dict[str, Any] | None) -> str:
    if obj is None:
        return "confirmed"
    attrs = obj if isinstance(obj, dict) else getattr(obj, "attrs", None) or {}
    status = str(attrs.get("status") or "").strip().lower()
    if status in {"unconfirmed", "confirmed", "rejected"}:
        return status
    if getattr(obj, "kind", None) == "NAME" and attrs.get("documento_ausente"):
        return "unconfirmed"
    return "confirmed"


def is_unconfirmed(obj: FoundEntity | Entity | dict[str, Any] | None) -> bool:
    return entity_status(obj) == "unconfirmed"


def found_canonical_key(found: FoundEntity) -> str:
    key = canonical_key(found.kind, found.value)
    if found.kind == "NAME" and is_unconfirmed(found):
        tag = str((found.attrs or {}).get("candidate_key") or found.value)[:80]
        return f"{key}#cand:{collapse_name(tag)}"
    return key


def mark_unconfirmed(found: FoundEntity, *, reason: str, candidate_key: str) -> FoundEntity:
    attrs = dict(found.attrs or {})
    attrs["status"] = "unconfirmed"
    attrs["motivo"] = reason
    attrs["candidate_key"] = candidate_key
    found.attrs = attrs
    found.confidence = min(found.confidence, 0.45)
    return found


def mark_confirmed(found: FoundEntity, *, reason: str) -> FoundEntity:
    attrs = dict(found.attrs or {})
    attrs["status"] = "confirmed"
    attrs["motivo"] = reason
    found.attrs = attrs
    found.confidence = max(found.confidence, 0.85)
    return found
