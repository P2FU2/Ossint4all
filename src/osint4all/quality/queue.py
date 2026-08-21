"""Fila visível do caso: o que espera, falhou ou voltou vazio."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from osint4all.catalog.sources import SOURCE_CATALOG
from osint4all.db.models import Entity, ExpansionJob, Investigation, QueryLog
from osint4all.db.repository import enqueue_expand, job_counts, utcnow
from osint4all.graph.expand import kind_for_connector

_STATUS_LABEL = {
    "PENDING": "na fila",
    "RUNNING": "rodando",
    "FAILED": "falhou",
    "DONE": "feito",
}


def _when(stamp) -> str:
    if not stamp:
        return ""
    try:
        return stamp.strftime("%d/%m %H:%M")
    except Exception:
        return ""


def _name_map(session: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = session.scalars(select(Entity).where(Entity.id.in_(ids))).all()
    return {row.id: row.display_name for row in rows}


def _connector_label(name: str) -> str:
    meta = SOURCE_CATALOG.get(name) or {}
    return str(meta.get("label") or name)


def queue_board(session: Session, investigation_id: str, *, limit: int = 16, empty_hours: int = 6) -> dict[str, Any]:
    counts = job_counts(session, investigation_id)
    jobs = list(
        session.scalars(
            select(ExpansionJob)
            .where(ExpansionJob.investigation_id == investigation_id)
            .order_by(desc(ExpansionJob.created_at))
            .limit(80)
        )
    )
    names = _name_map(session, {job.entity_id for job in jobs})
    active: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for job in jobs:
        row = {
            "id": job.id,
            "entity_id": job.entity_id,
            "name": names.get(job.entity_id) or "nó",
            "status": job.status,
            "label": _STATUS_LABEL.get(job.status, job.status),
            "error": (job.last_error or "")[:240],
            "origin": "job",
            "when": _when(job.finished_at or job.started_at or job.created_at),
        }
        if job.status in {"PENDING", "RUNNING"}:
            active.append(row)
        elif job.status == "FAILED":
            failed.append(row)
    cutoff = utcnow() - timedelta(hours=max(1, empty_hours))
    logs = list(
        session.scalars(
            select(QueryLog)
            .where(QueryLog.investigation_id == investigation_id, QueryLog.created_at >= cutoff)
            .order_by(desc(QueryLog.created_at))
            .limit(40)
        )
    )
    log_names = _name_map(session, {row.entity_id for row in logs if row.entity_id})
    empty: list[dict[str, Any]] = []
    for log in logs:
        error = str((log.params or {}).get("error") or "")
        if not log.empty and not error:
            continue
        row = {
            "id": log.id,
            "entity_id": log.entity_id or "",
            "name": log_names.get(log.entity_id or "") or "nó",
            "connector": log.connector,
            "label": _connector_label(log.connector),
            "error": (error or "sem resultado nesta fonte")[:240],
            "kind": "fail" if error else "empty",
            "origin": "log",
            "when": _when(log.created_at),
        }
        if error:
            if len(failed) < limit:
                failed.append(row)
        elif len(empty) < limit:
            empty.append(row)
    source_fails = sum(1 for row in failed if row.get("origin") == "log")
    return {
        "active": active[:limit],
        "failed": failed[:limit],
        "empty": empty,
        "counts": counts,
        "source_fails": source_fails,
        "open": bool(active or failed),
    }


def requeue_job(session: Session, investigation_id: str, job_id: str) -> ExpansionJob | None:
    job = session.get(ExpansionJob, job_id)
    if not job or job.investigation_id != investigation_id:
        return None
    job.status = "PENDING"
    job.last_error = None
    job.attempt_count = 0
    job.started_at = None
    job.finished_at = None
    return job


def retry_empty_log(session: Session, investigation: Investigation, log_id: str, *, max_attempts: int = 3) -> ExpansionJob | None:
    log = session.get(QueryLog, log_id)
    if not log or log.investigation_id != investigation.id or not log.entity_id:
        return None
    entity = session.get(Entity, log.entity_id)
    if not entity:
        return None
    kind = kind_for_connector(log.connector)
    attrs = dict(entity.attrs or {})
    if kind:
        attrs["probe_kinds"] = [kind]
        entity.attrs = attrs
    return enqueue_expand(
        session,
        investigation=investigation,
        entity=entity,
        depth=entity.depth,
        max_attempts=max_attempts,
        force=True,
    )


def retry_all_failed(session: Session, investigation_id: str) -> int:
    rows = list(
        session.scalars(
            select(ExpansionJob).where(
                ExpansionJob.investigation_id == investigation_id,
                ExpansionJob.status == "FAILED",
            )
        )
    )
    for job in rows:
        job.status = "PENDING"
        job.last_error = None
        job.attempt_count = 0
        job.started_at = None
        job.finished_at = None
    if rows:
        session.flush()
    return len(rows)
