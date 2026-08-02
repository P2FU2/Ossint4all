"""Critérios de monitoramento."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings
from monitor_jus.db.models import Criterion, CriterionLink
from monitor_jus.pipeline.bootstrap import sync_criteria_from_config
from monitor_jus.security import mask_cnpj, mask_cpf


def _display_value(crit: Criterion) -> str:
    if crit.criterion_type == "CPF":
        return mask_cpf(crit.value)
    if crit.criterion_type in ("CNPJ", "EMPRESA") and any(ch.isdigit() for ch in crit.value):
        digits = "".join(c for c in crit.value if c.isdigit())
        if len(digits) == 14:
            return mask_cnpj(digits)
    return crit.value


def list_criteria(session: Session) -> dict[str, Any]:
    criteria = list(session.scalars(select(Criterion).order_by(Criterion.criterion_type, Criterion.value)).all())
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
        rows.append(
            {
                "id": c.id,
                "type": c.criterion_type,
                "value": _display_value(c),
                "label": c.label or "—",
                "active": c.active,
                "process_count": proc_count,
                "created_at": c.created_at.astimezone().strftime("%d/%m/%Y") if c.created_at else "—",
            }
        )
    return {"criteria": rows, "total": len(rows), "active": sum(1 for r in rows if r["active"])}


def sync_criteria(session: Session, settings: Settings) -> int:
    n = sync_criteria_from_config(session, settings)
    from monitor_jus.pipeline.discovery import backfill_oab_links_from_payloads

    backfill_oab_links_from_payloads(session)
    return n
