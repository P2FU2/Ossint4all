"""Converte DjenSearchCriteria → query params reais da Comunica API."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from monitor_jus.config import get_settings, load_yaml
from monitor_jus.sources.djen.criteria import DjenSearchCriteria


@lru_cache
def _param_map() -> dict[str, Any]:
    settings = get_settings()
    return load_yaml(settings.config_path("djen_param_map.yaml")) or {}


def build_query_params(criteria: DjenSearchCriteria) -> dict[str, str | int]:
    cfg = _param_map()
    mapping: dict[str, str] = dict(cfg.get("params") or {})
    defaults = cfg.get("defaults") or {}
    size = criteria.size or int(defaults.get("size") or 50)
    max_size = int(defaults.get("max_size") or 100)
    size = max(1, min(size, max_size))

    domain_values: dict[str, Any] = {
        "text": criteria.text,
        "lawyer_name": criteria.lawyer_name,
        "oab_number": criteria.oab_number,
        "oab_state": criteria.oab_state,
        "process_number": criteria.process_number,
        "court": criteria.court,
        "available_from": (
            criteria.available_from.isoformat() if criteria.available_from else None
        ),
        "available_until": (
            criteria.available_until.isoformat() if criteria.available_until else None
        ),
        "page": criteria.page,
        "size": size,
    }

    out: dict[str, str | int] = {}
    for domain_key, value in domain_values.items():
        if value is None or value == "":
            continue
        api_key = mapping.get(domain_key, domain_key)
        out[api_key] = value
    return out


def djen_base_url() -> str:
    cfg = _param_map()
    return str(cfg.get("base_url") or "https://comunicaapi.pje.jus.br/api/v1/comunicacao")
