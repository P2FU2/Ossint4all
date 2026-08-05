"""Probe manual do contrato Comunica API.

Uso: python -m monitor_jus.sources.djen.probe
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from monitor_jus.config import get_settings
from monitor_jus.logging_setup import get_logger, setup_logging
from monitor_jus.sources.djen.client import DjenClient
from monitor_jus.sources.djen.criteria import DjenSearchCriteria
from monitor_jus.sources.djen.params import build_query_params

logger = get_logger(__name__)


def _run_case(client: DjenClient, name: str, criteria: DjenSearchCriteria) -> dict[str, Any]:
    params = build_query_params(criteria)
    result: dict[str, Any] = {
        "name": name,
        "domain_criteria": criteria.__dict__,
        "query_params": params,
        "ok": False,
    }
    try:
        data = client.search(criteria)
        items = data.get("items") or []
        result.update(
            {
                "ok": True,
                "items": len(items),
                "total": data.get("total"),
                "sample_keys": sorted(list(items[0].keys())) if items else [],
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["error_code"] = getattr(exc, "code", None)
    return result


def main() -> None:
    setup_logging()
    settings = get_settings()
    client = DjenClient(settings)
    today = date.today()
    start = today - timedelta(days=3)

    cases = [
        (
            "periodo",
            DjenSearchCriteria(available_from=start, available_until=today, size=5),
        ),
        (
            "tribunal_stj",
            DjenSearchCriteria(
                court="STJ",
                available_from=start,
                available_until=today,
                size=5,
            ),
        ),
        (
            "oab_sp",
            DjenSearchCriteria(
                oab_number="138094",
                oab_state="SP",
                available_from=start,
                available_until=today,
                size=5,
            ),
        ),
        (
            "nome",
            DjenSearchCriteria(
                lawyer_name="Fernando Crespo Queiroz Neves",
                available_from=start,
                available_until=today,
                size=5,
            ),
        ),
        (
            "paginacao",
            DjenSearchCriteria(
                court="STJ",
                available_from=start,
                available_until=today,
                page=1,
                size=2,
            ),
        ),
        (
            "size_max",
            DjenSearchCriteria(
                court="STJ",
                available_from=start,
                available_until=today,
                size=200,
            ),
        ),
    ]

    report = {
        "health": client.health(),
        "cases": [_run_case(client, name, crit) for name, crit in cases],
    }

    out_dir = Path(settings.outbox_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "djen_probe.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\nSalvo em {out_path}")


if __name__ == "__main__":
    main()
