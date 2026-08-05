"""Roteamento dinâmico DataJud por CNJ/sigla — não depende só de tribunais_ativos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from monitor_jus.config import Settings, get_settings, load_monitoramentos, load_yaml
from monitor_jus.validators import TribunalResolver, normalize_cnj


@dataclass(frozen=True)
class ProcessSourceRoute:
    source: str
    datajud_alias: str | None = None
    requires_reconciliation: bool = False


def normalize_court(court: str | None) -> str | None:
    if not court:
        return None
    return court.strip().upper().replace(" ", "")


def _fontes_cfg(settings: Settings) -> dict[str, Any]:
    cfg = load_monitoramentos(settings)
    return dict(cfg.get("fontes") or {})


def resolve_process_source(
    process_number: str,
    court: str | None,
    *,
    settings: Settings | None = None,
) -> ProcessSourceRoute:
    settings = settings or get_settings()
    fontes = _fontes_cfg(settings)
    datajud_cfg = dict(fontes.get("datajud") or {})
    excluded = {
        normalize_court(c) for c in (datajud_cfg.get("excluded_courts") or []) if c
    }
    aliases_ativos = [
        str(a).strip() for a in (datajud_cfg.get("aliases_ativos") or []) if str(a).strip()
    ]

    normalized_court = normalize_court(court)
    parts = normalize_cnj(process_number)

    if normalized_court == "STF" or (parts and parts.segmento == "1"):
        return ProcessSourceRoute(source="STF_DJEN_PORTAL", datajud_alias=None)

    if normalized_court in excluded:
        return ProcessSourceRoute(
            source="DJEN_ONLY",
            datajud_alias=None,
            requires_reconciliation=True,
        )

    if not settings.datajud_enable or datajud_cfg.get("enabled") is False:
        return ProcessSourceRoute(
            source="DJEN_ONLY",
            datajud_alias=None,
            requires_reconciliation=True,
        )

    resolver = TribunalResolver(settings.config_path("tribunais.yaml"))
    alias: str | None = None
    if parts:
        resolved = resolver.resolve_from_cnj(parts.numero_formatado) or {}
        alias = resolved.get("alias")
        key = (resolved.get("key") or "").lower()
        if key == "stf" or not resolved.get("datajud_supported", True):
            return ProcessSourceRoute(source="STF_DJEN_PORTAL", datajud_alias=None)

    if not alias and normalized_court:
        tribunais = load_yaml(settings.config_path("tribunais.yaml")) or {}
        all_t = dict(tribunais.get("tribunais") or {})
        all_t.update(tribunais.get("tribunais_extras") or {})
        entry = all_t.get(normalized_court.lower())
        if isinstance(entry, dict):
            alias = entry.get("alias")

    if alias and aliases_ativos and alias not in aliases_ativos:
        return ProcessSourceRoute(
            source="DJEN_ONLY",
            datajud_alias=None,
            requires_reconciliation=True,
        )

    if alias:
        return ProcessSourceRoute(source="DATAJUD", datajud_alias=str(alias))

    return ProcessSourceRoute(
        source="DJEN_ONLY",
        datajud_alias=None,
        requires_reconciliation=True,
    )
