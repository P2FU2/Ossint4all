"""Máscaras e redaction de dados sensíveis."""

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


def redact_text(text: str) -> str:
    """Remove CPF/CNPJ aparentes de logs."""
    if not text:
        return text
    text = re.sub(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "***CPF***", text)
    text = re.sub(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", "***CNPJ***", text)
    return text
