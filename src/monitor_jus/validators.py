"""Validação de CPF, CNPJ, OAB e número CNJ + inferência de tribunal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from monitor_jus.security import only_digits


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
    """Normaliza número OAB preservando sufixo alfabético (ex.: 2556A)."""
    raw = (numero or "").strip().upper().replace(" ", "")
    return re.sub(r"[^0-9A-Z]", "", raw)


def validate_oab(numero: str, seccional: str) -> bool:
    num = normalize_oab_numero(numero)
    digits = only_digits(num)
    sec = (seccional or "").strip().upper()
    return bool(digits) and 3 <= len(digits) <= 7 and len(sec) == 2 and sec.isalpha()


_CNJ_MASKED = re.compile(
    r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$"
)
_CNJ_DIGITS = re.compile(r"^\d{20}$")


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
    # NNNNNNNDDAAAAJTROOOO (20 dígitos)
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


class TribunalResolver:
    def __init__(self, tribunais_yaml: Path) -> None:
        data = yaml.safe_load(tribunais_yaml.read_text(encoding="utf-8")) or {}
        self.tribunais: dict[str, Any] = dict(data.get("tribunais") or {})
        self.tribunais.update(data.get("tribunais_extras") or {})
        self.segmento_tribunal: dict[str, str] = {
            str(k): str(v) for k, v in (data.get("segmento_tribunal") or {}).items()
        }

    def resolve_from_cnj(self, numero: str) -> dict[str, Any] | None:
        parts = normalize_cnj(numero)
        if not parts:
            return None
        # STF — sem endpoint DataJud
        if parts.segmento == "1":
            return {
                "key": "stf",
                "alias": None,
                "nome": "STF",
                "datajud_supported": False,
                "segmento": parts.segmento,
                "tribunal_code": parts.tribunal,
            }
        key = self.segmento_tribunal.get(f"{parts.segmento}.{parts.tribunal}")
        if not key:
            return {
                "key": None,
                "alias": None,
                "nome": None,
                "datajud_supported": False,
                "segmento": parts.segmento,
                "tribunal_code": parts.tribunal,
            }
        info = self.tribunais.get(key) or {}
        return {
            "key": key,
            "alias": info.get("alias"),
            "nome": info.get("nome"),
            "datajud_supported": bool(info.get("alias")),
            "segmento": parts.segmento,
            "tribunal_code": parts.tribunal,
        }
