"""Critérios de busca DJEN em vocabulário de domínio (não params da API)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DjenSearchCriteria:
    text: str | None = None
    lawyer_name: str | None = None
    oab_number: str | None = None
    oab_state: str | None = None
    process_number: str | None = None
    court: str | None = None
    available_from: date | None = None
    available_until: date | None = None
    page: int = 1
    size: int = 50
