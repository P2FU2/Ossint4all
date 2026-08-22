"""Regras de identidade: nome não confirma pessoa; âncora forte ou QSA sim."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from osint4all.db.models import Entity
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import validate_cpf

if TYPE_CHECKING:
    from osint4all.connectors.base import FoundEntity

MAX_GRAPH_DEPTH = 6


@dataclass(frozen=True)
class TargetProfile:
    """Âncoras do alvo neste caso. Nome sozinho não segura identidade."""

    name: str = ""
    cpf: str = ""
    emails: frozenset[str] = field(default_factory=frozenset)
    phones: frozenset[str] = field(default_factory=frozenset)
    birth: str = ""
    cnpjs: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_person_anchor(self) -> bool:
        return bool(self.cpf or self.emails or self.phones or self.birth)


def profile_from_fields(fields: dict[str, str] | None) -> TargetProfile:
    bag = {str(k).upper(): str(v or "").strip() for k, v in (fields or {}).items() if str(v or "").strip()}
    cpf = only_digits(bag.get("CPF") or "")
    emails = frozenset({bag["EMAIL"].lower()}) if bag.get("EMAIL") else frozenset()
    phones = frozenset({only_digits(bag["PHONE"])}) if bag.get("PHONE") else frozenset()
    cnpj = only_digits(bag.get("CNPJ") or "")
    return TargetProfile(
        name=bag.get("NAME") or "",
        cpf=cpf if validate_cpf(cpf) else "",
        emails=emails,
        phones=phones if len(next(iter(phones), "")) >= 10 else frozenset(),
        birth=bag.get("BIRTHDATE") or bag.get("NASCIMENTO") or "",
        cnpjs=frozenset({cnpj}) if len(cnpj) == 14 else frozenset(),
    )


def bind_found_to_profile(found: FoundEntity, profile: TargetProfile | None) -> str:
    """keep | skip | remap — sócio com o mesmo nome do alvo vira ligação, não clone."""
    if not profile:
        return "keep"
    label = str(getattr(found, "display_name", "") or getattr(found, "value", "") or "")
    same_name = bool(profile.name and names_same_person(label, profile.name))
    kind = str(getattr(found, "kind", "") or "").upper()
    if kind == "CPF":
        digits = only_digits(str(getattr(found, "value", "") or ""))
        if profile.cpf and digits == profile.cpf:
            return "keep"
        if profile.cpf and digits != profile.cpf and same_name:
            return "skip"
        return "keep"
    if kind == "NAME" and same_name:
        return "remap"
    attrs = getattr(found, "attrs", None) or {}
    overlap = name_overlap_score(label, profile.name) if profile.name else 0.0
    papel = str(attrs.get("papel") or "").strip().lower()
    try:
        match_n = int(attrs.get("identity_match") or 0)
    except (TypeError, ValueError):
        match_n = 0
    if kind == "NAME" and overlap >= 0.5 and (papel in {"parlamentar", "candidato", "pep"} or match_n >= 50):
        return "remap"
    if kind in {"EMAIL", "PHONE", "USERNAME", "BIRTHDATE"} and same_name:
        return "remap"
    return "keep"


def seed_fits_profile(kind: str, value: str, display_name: str, profile: TargetProfile | None) -> bool:
    """Impede gravar no caso o mesmo nome com outro CPF."""
    if not profile or not profile.has_person_anchor:
        return True
    kind = (kind or "").upper()
    label = display_name or value or ""
    if kind == "CPF" and profile.cpf:
        digits = only_digits(value)
        if digits != profile.cpf and profile.name and names_match(label, profile.name):
            return False
    if kind == "NAME" and profile.cpf and profile.name and names_match(value, profile.name):
        return False
    return True


def collapse_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.strip()).casefold()


def name_tokens(value: str) -> list[str]:
    return [token for token in collapse_name(value).split() if token]


def names_match(left: str, right: str) -> bool:
    a, b = collapse_name(left), collapse_name(right)
    return bool(a) and a == b


def name_search_variants(nome: str) -> list[str]:
    """Consultas curtas para APIs que não aceitam o nome civil inteiro."""
    skip = {"da", "de", "do", "dos", "das", "e", "di"}
    tokens = [t for t in name_tokens(nome) if t not in skip and len(t) > 1]
    out: list[str] = []
    seen: set[str] = set()
    for item in (nome.strip(), " ".join(tokens[-2:]) if len(tokens) >= 2 else "", " ".join(tokens[:2]) if len(tokens) >= 2 else ""):
        key = collapse_name(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def name_overlap_score(left: str, right: str) -> float:
    """0–1: fração de tokens (sem da/de/do) em comum. ≥0.5 costuma ser a mesma pessoa."""
    skip = {"da", "de", "do", "dos", "das", "e", "di"}
    a = {t for t in name_tokens(left) if t not in skip and len(t) > 1}
    b = {t for t in name_tokens(right) if t not in skip and len(t) > 1}
    if not a or not b:
        return 0.0
    if names_match(left, right) or names_same_person(left, right):
        return 1.0
    return len(a & b) / max(len(a), len(b))


def names_same_person(left: str, right: str) -> bool:
    """Nome completo igual, ou o mais curto (3+ tokens) cabe no mais longo."""
    if names_match(left, right):
        return True
    a, b = name_tokens(left), name_tokens(right)
    if len(a) < 3 or len(b) < 3:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return all(token in long for token in short)


def name_search_blocked(name: str, profile: TargetProfile | None) -> bool:
    """Só bloqueia busca por nome do próprio alvo quando o caso já tem âncora."""
    if not profile or not profile.has_person_anchor or not profile.name:
        return False
    return names_match(name or "", profile.name)


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


def is_active_node(obj: FoundEntity | Entity | dict[str, Any] | None) -> bool:
    return entity_status(obj) not in {"false", "rejected", "contested"}


def should_enqueue_child(found: FoundEntity, entity: Entity, profile: TargetProfile | None = None) -> bool:
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
    if found_type == "ORG" and is_unconfirmed(found):
        return False
    if profile and profile.has_person_anchor and not has_expandable_anchor(found):
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
