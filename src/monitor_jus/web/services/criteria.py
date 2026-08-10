"""Critérios de monitoramento."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, load_monitoramentos
from monitor_jus.db.models import Criterion, CriterionLink
from monitor_jus.logging_setup import get_logger
from monitor_jus.pipeline.bootstrap import sync_criteria_detailed
from monitor_jus.security import mask_cnpj, mask_cpf
from monitor_jus.validators import normalize_oab_numero, validate_oab

logger = get_logger(__name__)


def _display_value(crit: Criterion) -> str:
    if crit.criterion_type == "CPF":
        return mask_cpf(crit.value)
    if crit.criterion_type in ("CNPJ", "EMPRESA") and any(ch.isdigit() for ch in crit.value):
        digits = "".join(c for c in crit.value if c.isdigit())
        if len(digits) == 14:
            return mask_cnpj(digits)
    return crit.value


def _yaml_preview(settings: Settings) -> dict[str, Any]:
    path = Path(settings.monitoramentos_path)
    cfg = load_monitoramentos(settings)
    mon = cfg.get("monitoramentos") or {}
    oabs = []
    for oab in mon.get("oabs") or []:
        numero = normalize_oab_numero(str(oab.get("numero", "")))
        sec = str(oab.get("seccional", "")).upper()
        if validate_oab(numero, sec):
            oabs.append(
                {
                    "value": f"{sec}:{numero}",
                    "label": oab.get("responsavel") or "—",
                }
            )
    return {
        "yaml_path": str(path),
        "yaml_exists": path.exists(),
        "yaml_oabs": oabs,
    }


def list_criteria(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    from monitor_jus.web.services.coverage_health import criterion_poll_health

    criteria = list(
        session.scalars(select(Criterion).order_by(Criterion.criterion_type, Criterion.value)).all()
    )
    health = criterion_poll_health(session)
    rows = []
    for c in criteria:
        proc_count = int(
            session.scalar(
                select(func.count())
                .select_from(CriterionLink)
                .where(CriterionLink.criterion_id == c.id, CriterionLink.process_id.is_not(None))
            )
            or 0
        )
        h = health.get(c.id) or {
            "badge": "nunca",
            "last_success_at_fmt": "—",
            "last_failure_at_fmt": "—",
            "hit_max_pages_recent": False,
            "stale": True,
        }
        rows.append(
            {
                "id": c.id,
                "type": c.criterion_type,
                "value": _display_value(c),
                "label": c.label or "—",
                "active": c.active,
                "process_count": proc_count,
                "created_at": c.created_at.astimezone().strftime("%d/%m/%Y") if c.created_at else "—",
                "poll_badge": h.get("badge") or "nunca",
                "last_poll_ok": h.get("last_success_at_fmt") or "—",
                "last_poll_fail": h.get("last_failure_at_fmt") or "—",
                "hit_max_pages": bool(h.get("hit_max_pages_recent")),
                "poll_stale": bool(h.get("stale")),
            }
        )
    out: dict[str, Any] = {
        "criteria": rows,
        "total": len(rows),
        "active": sum(1 for r in rows if r["active"]),
    }
    if settings is not None:
        out.update(_yaml_preview(settings))
    return out


def sync_criteria(session: Session, settings: Settings) -> dict[str, Any]:
    """
    Sincroniza YAML → banco. Backfill de vínculos OAB é best-effort
    (falha no backfill NÃO desfaz a sync).
    """
    result = sync_criteria_detailed(session, settings)
    session.flush()

    backfilled = 0
    backfill_error = None
    try:
        from monitor_jus.pipeline.discovery import backfill_oab_links_from_payloads

        # SAVEPOINT: falha no backfill não desfaz a sync do YAML
        with session.begin_nested():
            backfilled = backfill_oab_links_from_payloads(session)
    except Exception as exc:  # noqa: BLE001
        backfill_error = str(exc)[:240]
        logger.warning(
            "criteria_sync_backfill_failed",
            extra={"extra": {"error": backfill_error}},
        )

    result["oab_links_backfilled"] = backfilled
    result["backfill_error"] = backfill_error
    return result
