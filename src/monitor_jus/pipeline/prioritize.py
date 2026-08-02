"""Prioridade determinística via YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from monitor_jus.config import load_yaml
from monitor_jus.models import Priority


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k.lower() in text for k in keywords)


def classify_priority(text: str, config_path: Path) -> tuple[Priority, str]:
    cfg = load_yaml(config_path)
    blob = (text or "").lower()
    has_intimacao = _contains_any(blob, ["intimação", "intimacao", "intimado"])
    has_sentenca = _contains_any(
        blob, ["sentença", "sentenca", "acórdão", "acordao", "julgado"]
    )
    has_prazo = _contains_any(blob, ["prazo", "dias úteis", "dias uteis"])
    has_audiencia = _contains_any(blob, ["audiência", "audiencia"])

    # regras compostas primeiro
    if has_sentenca and has_intimacao:
        return Priority.ALTA, "sentenca_com_intimacao"
    if has_prazo:
        return Priority.ALTA, "prazo_explicito"
    if has_audiencia:
        return Priority.ALTA, "audiencia_futura"
    if has_intimacao:
        return Priority.ALTA, "intimacao"
    if has_sentenca:
        return Priority.MEDIA, "sentenca_isolada"

    for rule in cfg.get("regras") or []:
        kws = rule.get("keywords") or []
        if kws and _contains_any(blob, kws):
            prio = Priority(rule.get("prioridade", "media"))
            return prio, str(rule.get("id") or "rule")

    default = cfg.get("default_prioridade", "media")
    return Priority(default), "default"


def has_possible_deadline(text: str) -> bool:
    blob = (text or "").lower()
    return any(k in blob for k in ("prazo", "dias úteis", "dias uteis", "intempest"))
