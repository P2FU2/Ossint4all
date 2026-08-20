"""Tarefas do caso."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import CaseTask, Investigation
from osint4all.db.repository import utcnow


def list_tasks(session: Session, investigation_id: str) -> list[CaseTask]:
    return list(
        session.scalars(
            select(CaseTask).where(CaseTask.investigation_id == investigation_id).order_by(CaseTask.created_at.desc())
        ).all()
    )


def add_task(
    session: Session,
    investigation: Investigation,
    *,
    title: str,
    body: str = "",
    assignee: str | None = None,
    created_by: str | None = None,
    due_at: datetime | None = None,
) -> CaseTask:
    row = CaseTask(
        investigation_id=investigation.id,
        title=(title or "Tarefa").strip()[:255] or "Tarefa",
        body=(body or "").strip()[:4000],
        assignee=(assignee or "").strip() or None,
        created_by=created_by,
        due_at=due_at,
        status="OPEN",
    )
    session.add(row)
    return row


def set_task_status(session: Session, investigation_id: str, task_id: str, *, done: bool) -> CaseTask | None:
    row = session.scalar(select(CaseTask).where(CaseTask.id == task_id, CaseTask.investigation_id == investigation_id))
    if not row:
        return None
    row.status = "DONE" if done else "OPEN"
    row.done_at = utcnow() if done else None
    return row
