"""Chaves canônicas e detecção de sementes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from osint4all.security import only_digits
from osint4all.validators import (
    format_plate,
    looks_like_email,
    looks_like_phone,
    looks_like_plate,
    looks_like_url,
    looks_like_username,
    normalize_cnj,
    normalize_oab_numero,
    normalize_plate,
    validate_cnpj,
    validate_cpf,
)

STRONG_ID_KINDS = frozenset({"CPF", "CNPJ", "CNJ", "EMAIL"})


@dataclass(frozen=True)
class ParsedSeed:
    kind: str
    value: str
    canonical_key: str
    entity_type: str
    display_name: str


def _collapse_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def canonical_key(kind: str, value: str) -> str:
    kind = kind.upper()
    if kind == "CPF":
        return f"cpf:{only_digits(value)}"
    if kind == "CNPJ":
        return f"cnpj:{only_digits(value)}"
    if kind == "CNJ":
        parts = normalize_cnj(value)
        return f"cnj:{parts.numero_digits}" if parts else f"cnj:{only_digits(value)}"
    if kind == "OAB":
        raw = (value or "").strip().upper()
        if ":" in raw:
            uf, _, num = raw.partition(":")
        elif "/" in raw:
            num, _, uf = raw.partition("/")
        else:
            uf, num = "", raw
        return f"oab:{uf.strip()}:{normalize_oab_numero(num)}"
    if kind == "EMAIL":
        return f"email:{(value or '').strip().lower()}"
    if kind == "PHONE":
        return f"phone:{only_digits(value)}"
    if kind == "USERNAME":
        return f"username:{(value or '').strip().lstrip('@').lower()}"
    if kind == "URL":
        return f"url:{(value or '').strip().rstrip('/').lower()}"
    if kind == "PLATE":
        return f"plate:{normalize_plate(value)}"
    if kind == "NAME":
        return f"name:{_collapse_name(value).casefold()}"
    return f"{kind.lower()}:{(value or '').strip().casefold()}"


def entity_type_for_kind(kind: str) -> str:
    return {
        "CPF": "PERSON",
        "NAME": "PERSON",
        "OAB": "PERSON",
        "EMAIL": "PERSON",
        "PHONE": "PERSON",
        "CNPJ": "ORG",
        "CNJ": "CASE",
        "USERNAME": "PROFILE",
        "URL": "PROFILE",
        "PLATE": "VEHICLE",
    }.get(kind.upper(), "PERSON")


def parse_seed(raw: str, *, forced_kind: str | None = None) -> ParsedSeed | None:
    text = (raw or "").strip()
    if not text:
        return None
    kind = (forced_kind or "").upper() or None
    if kind == "AUTO" or kind is None:
        kind = detect_kind(text)
    if not kind:
        return None
    key = canonical_key(kind, text)
    display = text.lstrip("@")
    if kind == "CNJ":
        parts = normalize_cnj(text)
        display = parts.numero_formatado if parts else text
    elif kind == "NAME":
        display = _collapse_name(text)
    elif kind == "USERNAME":
        display = text.lstrip("@")
    elif kind == "PLATE":
        display = format_plate(text)
    return ParsedSeed(
        kind=kind,
        value=text,
        canonical_key=key,
        entity_type=entity_type_for_kind(kind),
        display_name=display,
    )


def detect_kind(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if looks_like_url(text):
        return "URL"
    if looks_like_email(text):
        return "EMAIL"
    if validate_cnpj(text):
        return "CNPJ"
    if validate_cpf(text):
        return "CPF"
    if normalize_cnj(text):
        return "CNJ"
    if looks_like_plate(text):
        return "PLATE"
    if looks_like_phone(text) and not any(c.isalpha() for c in text):
        return "PHONE"
    oab = re.match(r"^(\d{3,7}[A-Z]?)\s*/\s*([A-Z]{2})$", text.upper())
    if oab:
        return "OAB"
    if text.startswith("@") and looks_like_username(text):
        return "USERNAME"
    if " " in text or any(c.isalpha() for c in text):
        return "NAME"
    if looks_like_username(text):
        return "USERNAME"
    return None


def parse_seed_lines(blob: str) -> list[ParsedSeed]:
    seen: set[str] = set()
    out: list[ParsedSeed] = []
    for line in (blob or "").splitlines():
        seed = parse_seed(line)
        if seed and seed.canonical_key not in seen:
            seen.add(seed.canonical_key)
            out.append(seed)
    return out
