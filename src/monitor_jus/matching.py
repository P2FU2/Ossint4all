"""Classificação de match: descoberta ≠ confirmação."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monitor_jus.canonical_oab import CanonicalOab, canonicalize_oab, OabCanonicalizeError
from monitor_jus.security import only_digits
from monitor_jus.validators import normalize_cnj


class MatchStatus(StrEnum):
    CONFIRMED_OAB = "CONFIRMED_OAB"
    CONFIRMED_PROCESS = "CONFIRMED_PROCESS"
    PROBABLE_NAME = "PROBABLE_NAME"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"
    PENDING_CNA = "PENDING_CNA"


@dataclass(frozen=True)
class MonitoredCriterion:
    criterion_type: str
    value: str
    label: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    requires_secondary_evidence: bool = False

    @property
    def oab(self) -> CanonicalOab | None:
        if self.criterion_type != "OAB":
            return None
        try:
            return canonicalize_oab(self.value)
        except OabCanonicalizeError:
            return None


@dataclass(frozen=True)
class MatchEvidence:
    status: MatchStatus
    reasons: list[str] = field(default_factory=list)
    matched_criteria: list[str] = field(default_factory=list)
    oabs_found: list[str] = field(default_factory=list)
    names_found: list[str] = field(default_factory=list)
    process_number: str | None = None


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _name_is_full_match(found: str, monitored: str) -> bool:
    a, b = _norm_name(found), _norm_name(monitored)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _name_is_fragment(found: str, monitored: str) -> bool:
    a, b = _norm_name(found), _norm_name(monitored)
    if not a or not b:
        return False
    parts = b.split()
    if len(parts) < 2:
        return False
    # fragmento: menos de 3 tokens do nome completo e não é igualdade
    found_parts = a.split()
    if len(found_parts) >= 3 and _name_is_full_match(found, monitored):
        return False
    return any(p in a for p in parts if len(p) > 2) and not _name_is_full_match(found, monitored)


def extract_oabs_from_text(text: str, *, default_state: str | None = None) -> list[CanonicalOab]:
    found: list[CanonicalOab] = []
    seen: set[str] = set()
    blob = text or ""
    for m in re.finditer(
        r"(?:OAB[\s./-]*)?(?:[A-Z]{2}[\s./-]*)?\d{3,7}[A-Z]?(?:[\s./-]*[A-Z]{2})?",
        blob,
        re.IGNORECASE,
    ):
        try:
            oab = canonicalize_oab(m.group(0), default_state=default_state)
        except OabCanonicalizeError:
            continue
        key = oab.canonical or f"{oab.number}{oab.suffix or ''}:{oab.state or '?'}"
        if key in seen:
            continue
        seen.add(key)
        found.append(oab)
    return found


def classify_match(
    *,
    process_number: str | None,
    court: str | None,
    text: str,
    lawyer_names: list[str],
    oabs: list[CanonicalOab],
    criteria: list[MonitoredCriterion],
) -> MatchEvidence:
    reasons: list[str] = []
    matched: list[str] = []
    oab_strs = [o.canonical or o.original for o in oabs]

    # Processos monitorados
    cnj = normalize_cnj(process_number or "")
    for crit in criteria:
        if crit.criterion_type != "PROCESSO":
            continue
        want = only_digits(crit.value)
        if cnj and want and cnj.numero_digits == want:
            matched.append(crit.value)
            return MatchEvidence(
                status=MatchStatus.CONFIRMED_PROCESS,
                reasons=["CNJ exato nos critérios"],
                matched_criteria=matched,
                oabs_found=oab_strs,
                names_found=lawyer_names,
                process_number=cnj.numero_formatado,
            )

    name_criteria = [c for c in criteria if c.criterion_type == "NOME"]
    full_name_hits: list[MonitoredCriterion] = []
    fragment_hits: list[MonitoredCriterion] = []
    blob = " ".join([text or "", *lawyer_names])

    for crit in name_criteria:
        monitored = crit.value or crit.label or ""
        for name in lawyer_names or [blob]:
            if _name_is_full_match(name, monitored):
                full_name_hits.append(crit)
                break
            if _name_is_fragment(name, monitored):
                fragment_hits.append(crit)

    # OAB exata (UF + número + sufixo) — coleta todas as OABs casadas
    oab_matched: list[str] = []
    oab_reasons: list[str] = []
    for crit in criteria:
        if crit.criterion_type != "OAB":
            continue
        crit_oab = crit.oab
        if not crit_oab or not crit_oab.state:
            continue
        for hit in oabs:
            if hit.matches_criterion(crit_oab):
                if crit.value not in oab_matched:
                    oab_matched.append(crit.value)
                    oab_reasons.append(f"OAB canônica {hit.canonical}")
                break
            # Mesmo número/UF com sufixo divergente → nunca confirmar
            if (
                hit.state == crit_oab.state
                and hit.digits == crit_oab.digits
                and (hit.suffix or None) != (crit_oab.suffix or None)
            ):
                reasons.append(
                    f"OAB {hit.canonical or hit.original} diverge do critério "
                    f"{crit_oab.canonical} (sufixo)"
                )

    if oab_matched:
        matched.extend(oab_matched)
        # Também vincula nome completo quando a OAB confirma a identidade
        matched.extend(c.value for c in full_name_hits if c.value not in matched)
        return MatchEvidence(
            status=MatchStatus.CONFIRMED_OAB,
            reasons=oab_reasons or ["OAB monitorada no registro"],
            matched_criteria=matched,
            oabs_found=oab_strs,
            names_found=lawyer_names,
            process_number=cnj.numero_formatado if cnj else process_number,
        )

    if full_name_hits and court:
        matched.extend(c.value for c in full_name_hits)
        return MatchEvidence(
            status=MatchStatus.PROBABLE_NAME,
            reasons=["Nome completo + tribunal relacionado"],
            matched_criteria=matched,
            oabs_found=oab_strs,
            names_found=lawyer_names,
            process_number=cnj.numero_formatado if cnj else process_number,
        )

    if fragment_hits:
        return MatchEvidence(
            status=MatchStatus.AMBIGUOUS,
            reasons=["Apenas fragmento de nome"],
            matched_criteria=[c.value for c in fragment_hits],
            oabs_found=oab_strs,
            names_found=lawyer_names,
            process_number=cnj.numero_formatado if cnj else process_number,
        )

    # OAB sem UF
    if any(o.state is None for o in oabs):
        return MatchEvidence(
            status=MatchStatus.AMBIGUOUS,
            reasons=["OAB sem UF — não confirmar"],
            oabs_found=oab_strs,
            names_found=lawyer_names,
            process_number=cnj.numero_formatado if cnj else process_number,
        )

    if reasons:
        return MatchEvidence(
            status=MatchStatus.REJECTED,
            reasons=reasons or ["OAB/nome divergente"],
            oabs_found=oab_strs,
            names_found=lawyer_names,
            process_number=cnj.numero_formatado if cnj else process_number,
        )

    if lawyer_names or oabs:
        return MatchEvidence(
            status=MatchStatus.REJECTED,
            reasons=["Nome/OAB sem correspondência aos critérios"],
            oabs_found=oab_strs,
            names_found=lawyer_names,
            process_number=cnj.numero_formatado if cnj else process_number,
        )

    return MatchEvidence(
        status=MatchStatus.AMBIGUOUS,
        reasons=["Sem evidências suficientes"],
        oabs_found=oab_strs,
        names_found=lawyer_names,
        process_number=cnj.numero_formatado if cnj else process_number,
    )
