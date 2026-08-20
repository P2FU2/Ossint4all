"""Validação de CPF, CNPJ, OAB e número CNJ."""

from __future__ import annotations

import re
from dataclasses import dataclass

from osint4all.security import only_digits


_CPF_MASK = re.compile(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$")
_BR_DDD = frozenset(
    {
        "11", "12", "13", "14", "15", "16", "17", "18", "19",
        "21", "22", "24", "27", "28",
        "31", "32", "33", "34", "35", "37", "38",
        "41", "42", "43", "44", "45", "46", "47", "48", "49",
        "51", "53", "54", "55",
        "61", "62", "63", "64", "65", "66", "67", "68", "69",
        "71", "73", "74", "75", "77", "79",
        "81", "82", "83", "84", "85", "86", "87", "88", "89",
        "91", "92", "93", "94", "95", "96", "97", "98", "99",
    }
)


def validate_cpf(cpf: str) -> bool:
    digits = only_digits(cpf)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for i in (9, 10):
        total = sum(int(digits[num]) * ((i + 1) - num) for num in range(0, i))
        digit = ((total * 10) % 11) % 10
        if digit != int(digits[i]):
            return False
    return True


def looks_like_cpf_mask(value: str) -> bool:
    return bool(_CPF_MASK.match((value or "").strip()))


def looks_like_br_mobile(value: str) -> bool:
    """Celular BR: DDD válido + 9 + 8 dígitos. Evita tratar telefone como CPF."""
    digits = only_digits(value)
    return len(digits) == 11 and digits[:2] in _BR_DDD and digits[2] == "9"


def socio_doc_matches_cpf(stored: str, cpf: str) -> bool:
    """Só aceita o documento do QSA se for o mesmo CPF (completo ou máscara oficial)."""
    if not validate_cpf(cpf):
        return False
    full = only_digits(cpf)
    raw = (stored or "").strip()
    if not raw:
        return False
    digits = only_digits(raw)
    if validate_cnpj(digits):
        return False
    if validate_cpf(digits):
        return digits == full
    if "*" in raw:
        visible = digits
        return len(visible) >= 6 and visible in full
    return False


def validate_cnpj(cnpj: str) -> bool:
    digits = only_digits(cnpj)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def calc(base: str, weights: list[int]) -> int:
        total = sum(int(a) * b for a, b in zip(base, weights))
        rest = total % 11
        return 0 if rest < 2 else 11 - rest

    d1 = calc(digits[:12], weights1)
    d2 = calc(digits[:12] + str(d1), weights2)
    return digits[-2:] == f"{d1}{d2}"


def normalize_oab_numero(numero: str) -> str:
    raw = (numero or "").strip().upper().replace(" ", "")
    return re.sub(r"[^0-9A-Z]", "", raw)


def validate_oab(numero: str, seccional: str) -> bool:
    num = normalize_oab_numero(numero)
    digits = only_digits(num)
    sec = (seccional or "").strip().upper()
    return bool(digits) and 3 <= len(digits) <= 7 and len(sec) == 2 and sec.isalpha()


_CNJ_MASKED = re.compile(r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$")
_CNJ_DIGITS = re.compile(r"^\d{20}$")
_EMAIL = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
_PHONE = re.compile(r"^\+?\d{10,15}$")
_PLATE = re.compile(r"^[A-Z]{3}-?\d[A-Z0-9]\d{2}$", re.I)
_USERNAME = re.compile(r"^@?[A-Za-z0-9._-]{2,40}$")


@dataclass(frozen=True)
class CNJParts:
    numero_digits: str
    numero_formatado: str
    segmento: str
    tribunal: str
    origem: str
    ano: str


def normalize_cnj(numero: str) -> CNJParts | None:
    raw = (numero or "").strip()
    m = _CNJ_MASKED.match(raw)
    if m:
        digits = "".join(m.groups())
        return CNJParts(
            numero_digits=digits,
            numero_formatado=raw,
            segmento=m.group(4),
            tribunal=m.group(5),
            origem=m.group(6),
            ano=m.group(3),
        )
    digits = only_digits(raw)
    if not _CNJ_DIGITS.match(digits):
        return None
    nnnnnnn, dd, aaaa, j, tr, oooo = (
        digits[0:7],
        digits[7:9],
        digits[9:13],
        digits[13:14],
        digits[14:16],
        digits[16:20],
    )
    formatted = f"{nnnnnnn}-{dd}.{aaaa}.{j}.{tr}.{oooo}"
    return CNJParts(
        numero_digits=digits,
        numero_formatado=formatted,
        segmento=j,
        tribunal=tr,
        origem=oooo,
        ano=aaaa,
    )


def validate_cnj(numero: str) -> bool:
    return normalize_cnj(numero) is not None


def looks_like_email(value: str) -> bool:
    return bool(_EMAIL.match((value or "").strip()))


def looks_like_phone(value: str) -> bool:
    return bool(_PHONE.match(only_digits(value) if value and value.strip().startswith("+") else only_digits(value))) and 10 <= len(only_digits(value)) <= 15


def normalize_plate(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def format_plate(value: str) -> str:
    plate = normalize_plate(value)
    if len(plate) == 7:
        return f"{plate[:3]}-{plate[3:]}"
    return plate


def looks_like_plate(value: str) -> bool:
    return bool(_PLATE.match((value or "").strip().replace(" ", "")))


def looks_like_username(value: str) -> bool:
    raw = (value or "").strip()
    if " " in raw or "." in raw and "@" in raw:
        return False
    return bool(_USERNAME.match(raw)) and not only_digits(raw) == raw.replace("@", "")


def looks_like_url(value: str) -> bool:
    raw = (value or "").strip().lower()
    return raw.startswith("http://") or raw.startswith("https://")
