"""Máscaras e extração de dígitos."""

from __future__ import annotations

import re


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def mask_cpf(cpf: str) -> str:
    digits = only_digits(cpf)
    if len(digits) != 11:
        return "***"
    return f"***.***.***-{digits[-2:]}"


def mask_cnpj(cnpj: str) -> str:
    digits = only_digits(cnpj)
    if len(digits) != 14:
        return "**"
    return f"**.***.***/****-{digits[-2:]}"


def mask_identifier(kind: str, value: str) -> str:
    if kind == "CPF":
        return mask_cpf(value)
    if kind == "CNPJ":
        return mask_cnpj(value)
    if kind in {"EMAIL", "PHONE"} and value:
        if "@" in value:
            name, _, domain = value.partition("@")
            return f"{name[:1]}***@{domain}"
        digits = only_digits(value)
        return f"***{digits[-4:]}" if len(digits) >= 4 else "***"
    if kind == "BANK" and value:
        digits = only_digits(value)
        if len(digits) >= 4:
            return f"conta ***{digits[-4:]}"
        return value
    return value
