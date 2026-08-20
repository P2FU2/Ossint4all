"""Regras de identidade: nome não confirma pessoa; âncora forte ou QSA sim."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from osint4all.db.models import Entity
from osint4all.identifiers import canonical_key

if TYPE_CHECKING:
    from osint4all.connectors.base import FoundEntity

MAX_GRAPH_DEPTH = 6


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
    if status == "rejected":
        return "false"
    if status in {"unconfirmed", "confirmed", "rejected", "probable", "contested", "false"}:
        return status
    if getattr(obj, "kind", None) == "NAME" and attrs.get("documento_ausente"):
        return "unconfirmed"
    return "confirmed"


def is_unconfirmed(obj: FoundEntity | Entity | dict[str, Any] | None) -> bool:
    return entity_status(obj) == "unconfirmed"


_EXPAND_PREFIXES = ("cnpj:", "cpf:", "email:", "phone:", "username:", "plate:", "cnj:")
_EXPAND_KINDS = frozenset({"CNPJ", "CPF", "EMAIL", "PHONE", "USERNAME", "PLATE", "CNJ"})


def is_qsa_partner(obj: FoundEntity | Entity | dict[str, Any] | None) -> bool:
    if obj is None:
        return False
    attrs = obj if isinstance(obj, dict) else getattr(obj, "attrs", None) or {}
    if attrs.get("papel") or attrs.get("documento_ausente"):
        return True
    return str(attrs.get("candidate_key") or "").startswith("qsa:")


def has_expandable_anchor(obj: FoundEntity | Entity | dict[str, Any] | None) -> bool:
    """CNPJ/CPF e outros IDs fortes podem expandir mesmo se o nó chegou como candidato."""
    if obj is None:
        return False
    kind = getattr(obj, "kind", None)
    if kind in _EXPAND_KINDS:
        return True
    key = str(getattr(obj, "canonical_key", "") or "")
    if key.startswith(_EXPAND_PREFIXES):
        return True
    attrs = obj if isinstance(obj, dict) else getattr(obj, "attrs", None) or {}
    return str(attrs.get("kind") or "") in _EXPAND_KINDS


def should_enqueue_child(found: FoundEntity, entity: Entity) -> bool:
    found_type = str(getattr(found, "entity_type", "") or "")
    entity_type = str(getattr(entity, "entity_type", "") or "")
    if found_type == "PROFILE" or entity_type == "PROFILE":
        return False
    if found_type == "PUBLICATION" or entity_type == "PUBLICATION":
        return False
    if entity_status(found) in {"false", "rejected", "contested"}:
        return False
    if entity_status(entity) in {"false", "rejected", "contested"}:
        return False
    if has_expandable_anchor(found) or has_expandable_anchor(entity):
        return True
    name = str(getattr(found, "display_name", "") or getattr(entity, "display_name", "") or "")
    if (
        (found_type == "PERSON" or entity_type == "PERSON")
        and (is_qsa_partner(found) or is_qsa_partner(entity))
        and not is_weak_name(name)
    ):
        return True
    return not (is_unconfirmed(found) or is_unconfirmed(entity))


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
