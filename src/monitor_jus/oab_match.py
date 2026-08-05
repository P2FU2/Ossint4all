"""Normalização e matching de OAB (critério, busca Judit, payload, filtros)."""

from __future__ import annotations

import json
import re
from typing import Any

from monitor_jus.security import only_digits
from monitor_jus.validators import normalize_oab_numero

# 2556/RJ · 2556A/RJ · OAB 2556/RJ · 2556-RJ
_OAB_SLASH = re.compile(
    r"(?:OAB\s*)?(\d{3,7}[A-Z]?)\s*[/\-]\s*([A-Z]{2})\b",
    re.IGNORECASE,
)
# Formato livre no filtro: 2556/RJ, OAB 2556 RJ, RJ:2556, 2556RJ
_OAB_FILTER = re.compile(
    r"^(?:oab\s*)?(?:([a-z]{2})\s*[:\s]+)?(\d{3,7}[a-z]?)(?:\s*[/\-\s]\s*([a-z]{2}))?$",
    re.IGNORECASE,
)


def oab_digits(numero: str) -> str:
    return only_digits(normalize_oab_numero(numero))


def oab_identity(numero: str, seccional: str) -> tuple[str, str]:
    """Chave estável: (dígitos, UF) — ignora sufixo A/B da inscrição suplementar."""
    return oab_digits(numero), (seccional or "").strip().upper()


def parse_oab_criterion_value(value: str) -> tuple[str, str] | None:
    """'RJ:2556A' → ('2556A', 'RJ')."""
    raw = (value or "").strip()
    if ":" not in raw:
        return None
    sec, numero = raw.split(":", 1)
    sec = sec.strip().upper()
    numero = normalize_oab_numero(numero)
    if not sec or not numero:
        return None
    return numero, sec


def oab_search_keys(numero: str, seccional: str) -> list[str]:
    """
    Chaves Judit a tentar: número+UF e, se houver letra, variante só com dígitos.
    Ex.: 2556A/RJ → ['2556ARJ', '2556RJ']
    """
    num = normalize_oab_numero(numero)
    sec = (seccional or "").strip().upper()
    if not num or not sec:
        return []
    keys = [f"{num}{sec}"]
    digits = only_digits(num)
    if digits and digits != num:
        alt = f"{digits}{sec}"
        if alt not in keys:
            keys.append(alt)
    return keys


def parse_oab_filter(text: str) -> tuple[str, str] | None:
    """Interpreta filtro do usuário → (digits, UF) ou None se texto livre."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _OAB_FILTER.match(raw.replace(" ", " ").strip())
    if not m:
        # tenta 2556/RJ embutido
        m2 = _OAB_SLASH.search(raw.upper())
        if m2:
            return oab_identity(m2.group(1), m2.group(2))
        return None
    sec = (m.group(1) or m.group(3) or "").upper()
    numero = m.group(2) or ""
    if not sec or not numero:
        return None
    return oab_identity(numero, sec)


def extract_oabs_from_payload(payload: Any) -> set[tuple[str, str]]:
    """Extrai identidades (digits, UF) de parties/lawyers, DJEN ou texto do payload."""
    found: set[tuple[str, str]] = set()
    if not payload:
        return found

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # DJEN destinatarioadvogados[].advogado: numero_oab + uf_oab (campos separados)
            numero = (
                node.get("numero_oab")
                or node.get("numeroOab")
                or node.get("numeroOAB")
            )
            uf = node.get("uf_oab") or node.get("ufOab") or node.get("ufOAB")
            if numero and uf:
                num = normalize_oab_numero(str(numero))
                sec = str(uf).strip().upper()
                if num and len(sec) == 2 and sec.isalpha():
                    found.add(oab_identity(num, sec))
            # Nesting comum: {"advogado": {"numero_oab": ..., "uf_oab": ...}}
            adv = node.get("advogado")
            if isinstance(adv, dict):
                walk(adv)

            doc_type = str(
                node.get("document_type")
                or node.get("type")
                or node.get("kind")
                or ""
            ).lower()
            doc = node.get("document") or node.get("number") or node.get("oab") or node.get("value")
            extra = (
                node.get("document_extra")
                or node.get("state")
                or node.get("uf")
                or node.get("seccional")
                or node.get("section")
            )
            if doc and (
                "oab" in doc_type
                or (isinstance(extra, str) and len(extra.strip()) == 2 and str(doc).strip())
            ):
                num = normalize_oab_numero(str(doc))
                sec = str(extra or "").strip().upper()
                if num and len(sec) == 2 and sec.isalpha():
                    found.add(oab_identity(num, sec))
            # lawyer.oab = "2556/RJ"
            for key in ("oab", "oab_number", "registration", "inscricao"):
                val = node.get(key)
                if isinstance(val, str) and "/" in val:
                    m = _OAB_SLASH.search(val.upper())
                    if m:
                        found.add(oab_identity(m.group(1), m.group(2)))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for m in _OAB_SLASH.finditer(node.upper()):
                found.add(oab_identity(m.group(1), m.group(2)))

    walk(payload)
    # fallback: dump textual (cobre formatos aninhados estranhos)
    try:
        blob = json.dumps(payload, ensure_ascii=False).upper()
    except (TypeError, ValueError):
        blob = str(payload).upper()
    for m in _OAB_SLASH.finditer(blob):
        found.add(oab_identity(m.group(1), m.group(2)))
    return found


def criterion_matches_oab(crit_value: str, identity: tuple[str, str]) -> bool:
    """Match tipado: UF+dígitos — UI/filtros. Confirmação forte usa CanonicalOab."""
    parsed = parse_oab_criterion_value(crit_value)
    if not parsed:
        return False
    return oab_identity(parsed[0], parsed[1]) == identity


def criterion_confirms_oab(crit_value: str, hit_numero: str, hit_uf: str) -> bool:
    """Confirmação forte: sufixo faz parte da identidade (RJ-2556 ≠ RJ-2556A)."""
    from monitor_jus.canonical_oab import canonicalize_oab, OabCanonicalizeError

    try:
        crit = canonicalize_oab(crit_value)
        hit = canonicalize_oab(f"{hit_uf}-{hit_numero}" if hit_uf else hit_numero, default_state=hit_uf)
    except OabCanonicalizeError:
        return False
    return crit.matches_criterion(hit)


def filter_matches_oab_text(filter_text: str, criteria_labels: str) -> bool:
    """True se o filtro (formato livre ou OAB) casa com o texto de critérios."""
    raw = (filter_text or "").strip().lower()
    if not raw:
        return True
    labels = (criteria_labels or "").lower()
    if raw in labels:
        return True
    identity = parse_oab_filter(filter_text)
    if not identity:
        return False
    digits, sec = identity
    # OAB 2556/RJ ou 2556A/RJ no label
    pattern = re.compile(
        rf"(?:oab\s*)?{re.escape(digits)}[a-z]?\s*/\s*{re.escape(sec.lower())}\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(labels))
