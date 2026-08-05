"""OAB canônica tipada — nunca inventa UF; sufixo é parte da identidade."""

from __future__ import annotations

import re
from dataclasses import dataclass

from monitor_jus.security import only_digits
from monitor_jus.validators import normalize_oab_numero

# Compacto: 138094SP / 2556ARJ / 2556A/RJ
_COMPACT = re.compile(
    r"^(?:OAB[\s./-]*)?(?P<number>\d{3,7})(?P<suffix>[A-Z])?(?:[\s./-]*)?(?P<uf>[A-Z]{2})$",
    re.IGNORECASE,
)
# Prefixo UF: OAB/SP 123.456 / SP-138094 / SP 138094A
_PREFIX_UF = re.compile(
    r"^(?:OAB[\s./-]*)?(?P<uf>[A-Z]{2})[\s./-]+(?P<body>\d[\d.\s]*[A-Z]?)$",
    re.IGNORECASE,
)
# Canônico: SP-123456 / RJ-2556A
_CANON = re.compile(r"^([A-Z]{2})-(\d{1,7})([A-Z])?$", re.IGNORECASE)

OAB_PATTERN = re.compile(
    r"""
    (?:OAB[\s./-]*)?
    (?:(?P<uf_before>[A-Z]{2})[\s./-]*)?
    (?P<number>\d{1,7}(?:[.\s]\d{3})*)
    [.\s/-]*
    (?P<suffix>[A-Z])?
    [.\s/-]*
    (?P<uf_after>[A-Z]{2})?
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class CanonicalOab:
    state: str | None
    number: str
    suffix: str | None
    canonical: str | None
    original: str

    @property
    def digits(self) -> str:
        return only_digits(self.number)

    def matches_criterion(self, other: CanonicalOab) -> bool:
        """Confirmação forte: UF + número + sufixo (null ≠ 'A')."""
        if not self.state or not other.state:
            return False
        if self.state != other.state:
            return False
        if self.digits != other.digits:
            return False
        return (self.suffix or None) == (other.suffix or None)


class OabCanonicalizeError(ValueError):
    pass


def canonicalize_oab(
    raw: str,
    *,
    default_state: str | None = None,
    require_state: bool = False,
) -> CanonicalOab:
    original = (raw or "").strip()
    if not original:
        raise OabCanonicalizeError("OAB vazia")

    # Formato critério legado UF:numero
    if ":" in original and len(original.split(":", 1)[0].strip()) == 2:
        sec, numero = original.split(":", 1)
        return _from_parts(
            state=sec.strip().upper(),
            numero=normalize_oab_numero(numero),
            original=original,
        )

    cleaned = original.upper().replace(" ", "")
    m_canon = _CANON.fullmatch(cleaned)
    if m_canon:
        return _from_parts(
            state=m_canon.group(1),
            numero=f"{m_canon.group(2)}{m_canon.group(3) or ''}",
            original=original,
        )

    m_compact = _COMPACT.fullmatch(cleaned)
    if m_compact:
        return _from_parts(
            state=m_compact.group("uf").upper(),
            numero=f"{m_compact.group('number')}{(m_compact.group('suffix') or '').upper()}",
            original=original,
        )

    m_prefix = _PREFIX_UF.fullmatch(original.strip())
    if m_prefix:
        body = normalize_oab_numero(m_prefix.group("body"))
        return _from_parts(
            state=m_prefix.group("uf").upper(),
            numero=body,
            original=original,
        )

    # Detecta UFs conflitantes explícitas (ex.: "SP 138094 RJ")
    ufs = re.findall(r"\b([A-Z]{2})\b", original.upper())
    digit_ufs = [u for u in ufs if u.isalpha()]
    if len(set(digit_ufs)) > 1:
        raise OabCanonicalizeError(f"UF conflitante na OAB: {original}")

    m = OAB_PATTERN.search(original.upper())
    if not m:
        raise OabCanonicalizeError(f"OAB inválida: {original}")

    uf_before = (m.group("uf_before") or "").upper() or None
    uf_after = (m.group("uf_after") or "").upper() or None
    if uf_before and uf_after and uf_before != uf_after:
        raise OabCanonicalizeError(f"UF conflitante na OAB: {original}")

    state = uf_before or uf_after
    if not state and default_state:
        ds = default_state.strip().upper()
        if len(ds) == 2 and ds.isalpha():
            state = ds

    number_raw = only_digits(m.group("number") or "")
    suffix = (m.group("suffix") or "").upper() or None
    # Evitar interpretar 1ª letra de UF como sufixo quando UF veio depois
    if suffix and uf_after is None and state is None and len(suffix) == 1:
        # ex.: falha residual — sem UF
        pass

    result = _from_parts(
        state=state,
        numero=f"{number_raw}{suffix or ''}",
        original=original,
    )
    if require_state and not result.state:
        raise OabCanonicalizeError(f"OAB sem UF: {original}")
    return result


def _from_parts(*, state: str | None, numero: str, original: str) -> CanonicalOab:
    num = normalize_oab_numero(numero)
    digits = only_digits(num)
    if not digits or len(digits) > 7:
        raise OabCanonicalizeError(f"Número OAB inválido: {original}")
    suffix_part = num[len(digits) :] if len(num) > len(digits) else ""
    suffix = suffix_part[:1] if suffix_part else None
    st = state.strip().upper() if state else None
    if st is not None and (len(st) != 2 or not st.isalpha()):
        st = None
    canonical = f"{st}-{digits}{suffix or ''}" if st else None
    return CanonicalOab(
        state=st,
        number=digits,
        suffix=suffix,
        canonical=canonical,
        original=original,
    )


def criterion_value_from_oab(oab: CanonicalOab) -> str:
    """Valor persistido em criteria: UF:numero[+sufixo]."""
    if not oab.state:
        raise OabCanonicalizeError("Critério OAB exige UF")
    return f"{oab.state}:{oab.number}{oab.suffix or ''}"
