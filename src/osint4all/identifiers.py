"""Chaves canônicas e detecção de sementes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from osint4all.security import only_digits
from osint4all.validators import (
    format_plate,
    looks_like_br_mobile,
    looks_like_cpf_mask,
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
CONSULT_MODE_KINDS = frozenset({"AUTO", "MASSA", "FILE", "PROCESSOS", "NEGATIVA", "IMOVEL", "DIARIO"})


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
    if kind == "BIRTHDATE":
        stamp = normalize_birth(value) or (value or "").strip()
        return f"birth:{only_digits(stamp)}"
    if kind == "FATHER":
        return f"father:{_collapse_name(value).casefold()}"
    if kind == "MOTHER":
        return f"mother:{_collapse_name(value).casefold()}"
    if kind == "BANK":
        return f"bank:{_collapse_name(value).casefold()}"
    if kind == "WEALTH":
        return f"wealth:{_collapse_name(value).casefold()}"
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
        "BIRTHDATE": "PERSON",
        "FATHER": "PERSON",
        "MOTHER": "PERSON",
        "BANK": "ASSET",
        "WEALTH": "ASSET",
    }.get(kind.upper(), "PERSON")


def parse_seed(raw: str, *, forced_kind: str | None = None) -> ParsedSeed | None:
    text = (raw or "").strip()
    if not text:
        return None
    kind = (forced_kind or "").upper() or None
    if kind is None or kind in CONSULT_MODE_KINDS:
        kind = detect_kind(text)
    if not kind:
        return None
    if kind == "CPF" and not validate_cpf(text):
        return None
    if kind == "CNPJ" and not validate_cnpj(text):
        return None
    if kind == "BIRTHDATE":
        stamp = normalize_birth(text)
        if not stamp:
            return None
        text = stamp
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
    elif kind == "BIRTHDATE":
        display = text
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
    if looks_like_cpf_mask(text) and validate_cpf(text):
        return "CPF"
    if looks_like_br_mobile(text) and not looks_like_cpf_mask(text):
        return "PHONE"
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


def normalize_birth(value: str) -> str | None:
    text = (value or "").strip()
    match = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        digits = only_digits(text)
        if len(digits) != 8:
            return None
        day, month, year = int(digits[:2]), int(digits[2:4]), int(digits[4:])
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100):
        return None
    return f"{day:02d}/{month:02d}/{year}"


def parse_seed_lines(blob: str) -> list[ParsedSeed]:
    return dedupe_seeds(parse_seed(line) for line in (blob or "").splitlines())


def dedupe_seeds(seeds) -> list[ParsedSeed]:
    seen: set[str] = set()
    out: list[ParsedSeed] = []
    for seed in seeds:
        if not seed or seed.canonical_key in seen:
            continue
        seen.add(seed.canonical_key)
        out.append(seed)
    return out


def seeds_from_kind_values(items) -> list[ParsedSeed]:
    return dedupe_seeds(parse_seed(value, forced_kind=kind or None) for kind, value in items if value)


def collect_form_seeds(
    seeds: str = "",
    *,
    seed_cpf: str = "",
    seed_cnpj: str = "",
    seed_name: str = "",
    seed_email: str = "",
    seed_phone: str = "",
    seed_username: str = "",
    seed_plate: str = "",
    seed_plate_owner: str = "",
    seed_plate_cpf: str = "",
    seed_cnj: str = "",
    seed_birth: str = "",
    seed_father: str = "",
    seed_mother: str = "",
) -> list[ParsedSeed]:
    extras = [
        parse_seed(seed_cpf, forced_kind="CPF"),
        parse_seed(seed_cnpj, forced_kind="CNPJ"),
        parse_seed(seed_name, forced_kind="NAME"),
        parse_seed(seed_email, forced_kind="EMAIL"),
        parse_seed(seed_phone, forced_kind="PHONE"),
        parse_seed(seed_username, forced_kind="USERNAME"),
        parse_seed(seed_cnj, forced_kind="CNJ"),
        parse_seed(seed_plate, forced_kind="PLATE") if looks_like_plate(seed_plate) else None,
        parse_seed(seed_plate_cpf, forced_kind="CPF"),
        parse_seed(seed_plate_owner, forced_kind="NAME"),
        parse_seed(seed_father, forced_kind="FATHER"),
        parse_seed(seed_mother, forced_kind="MOTHER"),
        parse_seed(seed_birth, forced_kind="BIRTHDATE"),
    ]
    return dedupe_seeds([*parse_seed_lines(seeds), *extras])
