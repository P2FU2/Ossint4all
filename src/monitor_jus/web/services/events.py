"""Lista de eventos e quarentena."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.db.models import Event, EventQuarantine, Process
from monitor_jus.security import redact_text


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


def list_events(
    session: Session,
    *,
    notify_status: str = "",
    priority: str = "",
    event_type: str = "",
    q: str = "",
    deadline_only: bool = False,
) -> dict[str, Any]:
    stmt = select(Event).order_by(Event.created_at.desc()).limit(300)
    events = list(session.scalars(stmt).all())

    ns = (notify_status or "").strip()
    pr = (priority or "").strip().lower()
    et = (event_type or "").strip()
    qn = (q or "").strip().lower()

    rows = []
    for e in events:
        if ns and e.notify_status != ns:
            continue
        if pr and (e.priority or "").lower() != pr:
            continue
        if et and e.event_type != et:
            continue
        if deadline_only and not e.possible_deadline_flag:
            continue
        blob = f"{e.numero_cnj or ''} {e.title or ''} {e.summary or ''}".lower()
        if qn and qn not in blob:
            continue
        process_id = None
        if e.numero_cnj:
            proc = session.scalar(select(Process).where(Process.numero_cnj == e.numero_cnj))
            process_id = proc.id if proc else None
        rows.append(
            {
                "id": e.id,
                "event_type": e.event_type,
                "title": e.title or e.event_type,
                "summary": redact_text((e.summary or e.description or "")[:280]),
                "priority": e.priority,
                "notify_status": e.notify_status,
                "numero_cnj": e.numero_cnj or "—",
                "tribunal": e.tribunal or "—",
                "area_juridica": e.area_juridica or "—",
                "possible_deadline_flag": e.possible_deadline_flag,
                "created_at": _fmt(e.created_at),
                "official_link": e.official_link,
                "process_id": process_id,
            }
        )

    quarantine = list(
        session.scalars(
            select(EventQuarantine)
            .where(EventQuarantine.resolved_at.is_(None))
            .order_by(EventQuarantine.created_at.desc())
            .limit(50)
        ).all()
    )

    types = sorted({e.event_type for e in events})
    return {
        "events": rows,
        "total": len(rows),
        "event_types": types,
        "quarantine": [
            {
                "id": qitem.id,
                "reason": qitem.reason,
                "details": redact_text((qitem.details or "")[:300]),
                "delivery_key": qitem.delivery_key or "—",
                "created_at": _fmt(qitem.created_at),
            }
            for qitem in quarantine
        ],
        "filters": {
            "notify_status": notify_status,
            "priority": priority,
            "event_type": event_type,
            "q": q,
            "deadline_only": deadline_only,
        },
    }


def get_event_detail(session: Session, event_id: str) -> dict[str, Any] | None:
    e = session.get(Event, event_id)
    if not e:
        return None
    process_id = None
    if e.numero_cnj:
        proc = session.scalar(select(Process).where(Process.numero_cnj == e.numero_cnj))
        process_id = proc.id if proc else None
    return {
        "id": e.id,
        "event_type": e.event_type,
        "title": e.title or e.event_type,
        "description": redact_text(e.description or ""),
        "summary": redact_text(e.summary or ""),
        "possible_action": redact_text(e.possible_action or ""),
        "priority": e.priority,
        "notify_status": e.notify_status,
        "numero_cnj": e.numero_cnj or "—",
        "tribunal": e.tribunal or "—",
        "area_juridica": e.area_juridica or "—",
        "tipo_movimentacao": e.tipo_movimentacao or "—",
        "possible_deadline_flag": e.possible_deadline_flag,
        "official_link": e.official_link,
        "criterion_refs": e.criterion_refs or [],
        "created_at": _fmt(e.created_at),
        "process_id": process_id,
        "source_name": e.source_name,
    }
