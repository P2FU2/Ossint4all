"""Detecção de mudança: o que entrou ou mudou no caso."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint4all.db.models import ChangeLog, Entity, Evidence, Investigation
from osint4all.db.repository import utcnow


def record_change(
    session: Session,
    investigation: Investigation,
    *,
    field: str,
    old_value: str,
    new_value: str,
    entity_id: str | None = None,
) -> ChangeLog | None:
    if (old_value or "") == (new_value or ""):
        return None
    row = ChangeLog(
        investigation_id=investigation.id,
        entity_id=entity_id,
        field=(field or "")[:64],
        old_value=(old_value or "")[:400],
        new_value=(new_value or "")[:400],
        detected_at=utcnow(),
    )
    session.add(row)
    return row


def recent_changes(session: Session, investigation_id: str, *, limit: int = 20) -> list[ChangeLog]:
    return list(
        session.scalars(
            select(ChangeLog)
            .where(ChangeLog.investigation_id == investigation_id)
            .order_by(ChangeLog.detected_at.desc())
            .limit(limit)
        ).all()
    )


def case_digest(session: Session, investigation_id: str) -> dict[str, int]:
    entities = session.scalar(select(func.count()).select_from(Entity).where(Entity.investigation_id == investigation_id)) or 0
    evidence = session.scalar(select(func.count()).select_from(Evidence).where(Evidence.investigation_id == investigation_id)) or 0
    changes = session.scalar(select(func.count()).select_from(ChangeLog).where(ChangeLog.investigation_id == investigation_id)) or 0
    return {"entities": int(entities), "evidence": int(evidence), "changes": int(changes)}


def desk_digest(session: Session, *, hours: int = 48, limit: int = 12) -> list[dict]:
    """O que mudou na mesa desde ontem — casos monitorados primeiro."""
    cutoff = utcnow() - timedelta(hours=max(6, hours))
    rows = list(
        session.scalars(
            select(ChangeLog)
            .where(ChangeLog.detected_at >= cutoff)
            .order_by(ChangeLog.detected_at.desc())
            .limit(40)
        )
    )
    if not rows:
        return []
    inv_ids = {row.investigation_id for row in rows}
    cases = {
        inv.id: inv
        for inv in session.scalars(select(Investigation).where(Investigation.id.in_(inv_ids), Investigation.status != "DELETED"))
    }
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        inv = cases.get(row.investigation_id)
        if not inv:
            continue
        mark = (inv.id, row.field + (row.new_value or ""))
        if mark in seen:
            continue
        seen.add(mark)
        out.append(
            {
                "case_id": inv.id,
                "case_title": inv.title,
                "monitor": bool(inv.monitor),
                "field": row.field,
                "old": row.old_value or "—",
                "new": row.new_value or "—",
                "when": row.detected_at.strftime("%d/%m %H:%M") if row.detected_at else "",
            }
        )
        if len(out) >= limit:
            break
    out.sort(key=lambda item: (not item["monitor"], item["when"]), reverse=False)
    return out
