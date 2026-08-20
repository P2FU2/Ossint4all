"""Linha do tempo persistida do caso."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import CaseEvent, Investigation
from osint4all.db.repository import utcnow


def add_event(
    session: Session,
    investigation: Investigation,
    *,
    event_type: str,
    title: str,
    meta: str = "",
    url: str | None = None,
    entity_id: str | None = None,
    evidence_id: str | None = None,
    occurred_at: datetime | None = None,
) -> CaseEvent:
    row = CaseEvent(
        investigation_id=investigation.id,
        entity_id=entity_id,
        evidence_id=evidence_id,
        event_type=(event_type or "evento")[:32],
        title=(title or "")[:255],
        meta=(meta or "")[:400],
        url=url,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(row)
    return row


def list_events(
    session: Session,
    investigation_id: str,
    *,
    entity_id: str | None = None,
    limit: int = 80,
) -> list[CaseEvent]:
    stmt = select(CaseEvent).where(CaseEvent.investigation_id == investigation_id)
    if entity_id:
        stmt = stmt.where(CaseEvent.entity_id == entity_id)
    return list(session.scalars(stmt.order_by(CaseEvent.occurred_at.desc()).limit(limit)).all())
