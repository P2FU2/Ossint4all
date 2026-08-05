"""Painel consolidado de acompanhamento (jobs ao vivo + histórico recente)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.db.models import Job, Run
from monitor_jus.db.repository import utcnow
from monitor_jus.models import JobStatus
from monitor_jus.progress import format_bar, format_eta, job_progress_dict

_STATUS_LABELS = {
    JobStatus.PENDING.value: "Na fila",
    JobStatus.RUNNING.value: "Em execução",
    JobStatus.RETRY.value: "Nova tentativa",
    JobStatus.SUCCESS.value: "Concluído",
    JobStatus.FAILED.value: "Falhou",
    JobStatus.DEAD.value: "Morto",
    JobStatus.CANCELLED.value: "Cancelado",
}

# Sem heartbeat recente → considerado travado na UI (mesmo antes do reap)
_STALE_HEARTBEAT = timedelta(minutes=25)
_STALE_NEVER_STARTED = timedelta(minutes=15)


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except Exception:  # noqa: BLE001
        return str(dt)[:19]


def _duration(start: Any, end: Any) -> str:
    if not start:
        return "—"
    finish = end or utcnow()
    try:
        secs = int((finish - start).total_seconds())
    except Exception:  # noqa: BLE001
        return "—"
    return format_eta(float(secs))


def _is_stale_running(job: Job) -> bool:
    if job.status != JobStatus.RUNNING.value:
        return False
    now = utcnow()
    hb = job.heartbeat_at or job.started_at or job.created_at
    if not hb:
        return True
    pct = int(job.progress_pct or 0)
    stage = (job.progress_stage or "").strip().lower()
    never_progressed = pct <= 0 and stage in ("", "starting", "—", "-")
    if never_progressed and (now - hb) >= _STALE_NEVER_STARTED:
        return True
    return (now - hb) >= _STALE_HEARTBEAT


def _serialize_job(job: Job, run: Run | None = None) -> dict[str, Any]:
    prog = job_progress_dict(job)
    stale = _is_stale_running(job)
    status = job.status
    status_label = _STATUS_LABELS.get(status, status)
    if stale:
        status_label = "Travado"
    can_cancel = status in (
        JobStatus.PENDING.value,
        JobStatus.RUNNING.value,
        JobStatus.RETRY.value,
    )
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": status,
        "status_label": status_label,
        "stale": stale,
        "can_cancel": can_cancel,
        "run_id": job.run_id,
        "run_type": run.run_type if run else "—",
        "trigger_type": run.trigger_type if run else "—",
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "created_at": _fmt(job.created_at),
        "started_at": _fmt(job.started_at),
        "finished_at": _fmt(job.finished_at),
        "heartbeat_at": _fmt(job.heartbeat_at),
        "duration": _duration(job.started_at, job.finished_at),
        "last_error": (job.last_error_message or "")[:280],
        **prog,
    }


def build_progress_board(session: Session) -> dict[str, Any]:
    active_statuses = [
        JobStatus.PENDING.value,
        JobStatus.RUNNING.value,
        JobStatus.RETRY.value,
    ]
    active_jobs = list(
        session.scalars(
            select(Job)
            .where(Job.status.in_(active_statuses))
            .order_by(Job.created_at.desc())
            .limit(40)
        ).all()
    )
    recent_jobs = list(
        session.scalars(
            select(Job)
            .where(
                Job.status.in_(
                    [
                        JobStatus.SUCCESS.value,
                        JobStatus.DEAD.value,
                        JobStatus.FAILED.value,
                        JobStatus.CANCELLED.value,
                    ]
                )
            )
            .order_by(Job.finished_at.desc().nulls_last(), Job.created_at.desc())
            .limit(30)
        ).all()
    )

    run_ids = {j.run_id for j in active_jobs + recent_jobs if j.run_id}
    runs = {
        r.id: r
        for r in session.scalars(select(Run).where(Run.id.in_(run_ids))).all()
    } if run_ids else {}

    active = [_serialize_job(j, runs.get(j.run_id) if j.run_id else None) for j in active_jobs]
    recent = [_serialize_job(j, runs.get(j.run_id) if j.run_id else None) for j in recent_jobs]

    healthy_running = [
        j
        for j in active
        if j["status"] == JobStatus.RUNNING.value and not j.get("stale")
    ]
    stale_running = [j for j in active if j.get("stale")]

    # Destaque: job saudável com mais progresso / heartbeat mais recente
    headline = None
    if healthy_running:
        headline = max(
            healthy_running,
            key=lambda j: (j.get("progress_pct") or 0, j.get("heartbeat_at") or ""),
        )
    elif active:
        headline = active[0]

    from monitor_jus.ops_config import ops_for_ui

    return {
        "active": active,
        "recent": recent,
        "headline": headline,
        "active_count": len(active),
        "running_count": len(healthy_running),
        "stale_count": len(stale_running),
        "pending_count": sum(1 for j in active if j["status"] == JobStatus.PENDING.value),
        "refreshed_at": _fmt(utcnow()),
        "empty_bar": format_bar(0),
        "ops": ops_for_ui(),
    }
