"""Categorização por área e tipo de movimentação."""

from __future__ import annotations

from pathlib import Path

from monitor_jus.config import load_yaml


def _match(text: str, items: list[dict]) -> str:
    blob = (text or "").lower()
    for item in items:
        kws = item.get("keywords") or []
        if not kws and item.get("id") == "outros":
            continue
        if any(k.lower() in blob for k in kws):
            return str(item["id"])
    return "outros"


def categorize(text: str, config_path: Path) -> tuple[str, str]:
    cfg = load_yaml(config_path)
    area = _match(text, cfg.get("areas_juridicas") or [])
    tipo = _match(text, cfg.get("tipos_movimentacao") or [])
    return area, tipo
