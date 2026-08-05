"""Config operacional editável pela UI (config/ops.yaml) — não via .env."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from monitor_jus.config import Settings, get_settings, load_yaml

OPS_FILENAME = "ops.yaml"

_DEFAULTS: dict[str, Any] = {
    "discovery": {
        "lookback_days": 1095,
        "max_pages": 80,
        "search_oabs": True,
        "search_names": True,
        "search_processes": True,
        "search_companies": True,
    },
    "bootstrap": {
        "lookback_days": 1095,
        "max_pages": 80,
        "complete_missing_capa": True,
        "ignore_events_for_digest": True,
    },
    "poll": {
        "overlap_hours": 48,
    },
}


def ops_path(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return s.config_path(OPS_FILENAME)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_ops(settings: Settings | None = None) -> dict[str, Any]:
    path = ops_path(settings)
    raw = load_yaml(path) if path.exists() else {}
    return _deep_merge(_DEFAULTS, raw if isinstance(raw, dict) else {})


def save_ops(data: dict[str, Any], settings: Settings | None = None) -> Path:
    """Persiste ops.yaml com merge sobre defaults (só chaves conhecidas)."""
    path = ops_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _sanitize(data)
    merged = _deep_merge(_DEFAULTS, cleaned)
    text = yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")
    return path


def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
    disc = data.get("discovery") if isinstance(data.get("discovery"), dict) else {}
    boot = data.get("bootstrap") if isinstance(data.get("bootstrap"), dict) else {}
    poll = data.get("poll") if isinstance(data.get("poll"), dict) else {}

    def _int(val: Any, default: int, lo: int, hi: int) -> int:
        try:
            n = int(val)
        except (TypeError, ValueError):
            n = default
        return max(lo, min(hi, n))

    def _bool(val: Any, default: bool = True) -> bool:
        if isinstance(val, bool):
            return val
        if val is None:
            return default
        return str(val).strip().lower() in {"1", "true", "yes", "on", "sim"}

    return {
        "discovery": {
            "lookback_days": _int(disc.get("lookback_days"), 1095, 7, 3650),
            "max_pages": _int(disc.get("max_pages"), 80, 5, 200),
            "search_oabs": _bool(disc.get("search_oabs"), True),
            "search_names": _bool(disc.get("search_names"), True),
            "search_processes": _bool(disc.get("search_processes"), True),
            "search_companies": _bool(disc.get("search_companies"), True),
        },
        "bootstrap": {
            "lookback_days": _int(boot.get("lookback_days"), 1095, 7, 3650),
            "max_pages": _int(boot.get("max_pages"), 80, 5, 200),
            "complete_missing_capa": _bool(boot.get("complete_missing_capa"), True),
            "ignore_events_for_digest": _bool(boot.get("ignore_events_for_digest"), True),
        },
        "poll": {
            "overlap_hours": _int(poll.get("overlap_hours"), 48, 1, 720),
        },
    }


def ops_for_ui(settings: Settings | None = None) -> dict[str, Any]:
    """Snapshot para templates."""
    ops = load_ops(settings)
    return {
        "path": str(ops_path(settings)),
        "discovery": ops["discovery"],
        "bootstrap": ops["bootstrap"],
        "poll": ops["poll"],
    }
