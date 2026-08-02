"""Status do pipeline, runs e jobs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings
from monitor_jus.db.models import (
    BootstrapState,
    Criterion,
    Digest,
    DigestCursor,
    Event,
    Job,
    JobDeadLetter,
    ProviderSubscription,
    Run,
    WebhookRaw,
)
from monitor_jus.db.repository import utcnow
from monitor_jus.models import JobStatus, NotifyStatus
from monitor_jus.progress import job_progress_dict
from monitor_jus.web.services.progress_board import build_progress_board


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


def _duration(start: Any, end: Any) -> str:
    if not start:
        return "—"
    finish = end or utcnow()
    try:
        secs = int((finish - start).total_seconds())
    except Exception:  # noqa: BLE001
        return "—"
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m {secs}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins}m"


def _stage(status: str, label: str, detail: str, count: int | None = None) -> dict[str, Any]:
    return {"status": status, "label": label, "detail": detail, "count": count}


def build_pipeline_status(session: Session, settings: Settings) -> dict[str, Any]:
    criteria_active = int(
        session.scalar(select(func.count()).select_from(Criterion).where(Criterion.active.is_(True)))
        or 0
    )
    bootstrap = session.get(BootstrapState, 1)
    running_discovery = session.scalar(
        select(Job)
        .where(
            Job.job_type.in_(["HISTORICAL_DISCOVERY", "BOOTSTRAP"]),
            Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value, JobStatus.RETRY.value]),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    last_discovery = session.scalar(
        select(Job)
        .where(Job.job_type.in_(["HISTORICAL_DISCOVERY", "BOOTSTRAP"]))
        .order_by(Job.created_at.desc())
        .limit(1)
    )

    sub_counts = {
        s: int(
            session.scalar(
                select(func.count()).select_from(ProviderSubscription).where(
                    ProviderSubscription.status == s
                )
            )
            or 0
        )
        for s in ("ACTIVE", "STALE", "ERROR", "PENDING")
    }
    pending_webhooks = int(
        session.scalar(
            select(func.count()).select_from(WebhookRaw).where(WebhookRaw.status == "PENDING")
        )
        or 0
    )
    pending_events = int(
        session.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.notify_status == NotifyStatus.PENDING_NOTIFY.value)
        )
        or 0
    )
    cursor = session.get(DigestCursor, 1)
    last_digest = session.scalar(select(Digest).order_by(Digest.created_at.desc()).limit(1))

    stages: list[dict[str, Any]] = []

    stages.append(
        _stage(
            "ok" if criteria_active else "erro",
            "Critérios ativos",
            f"{criteria_active} critério(s) sincronizado(s) do YAML",
            criteria_active,
        )
    )

    if bootstrap and bootstrap.completed:
        stages.append(
            _stage("ok", "Bootstrap / baseline", f"Concluído em {_fmt(bootstrap.baseline_at)}")
        )
    elif running_discovery and running_discovery.job_type == "BOOTSTRAP":
        stages.append(_stage("em_andamento", "Bootstrap / baseline", "Bootstrap em execução"))
    else:
        stages.append(_stage("atrasado", "Bootstrap / baseline", "Ainda não concluído"))

    if running_discovery:
        stages.append(
            _stage(
                "em_andamento",
                "Discovery",
                f"{running_discovery.job_type} · {running_discovery.status}",
            )
        )
    elif last_discovery and last_discovery.status == JobStatus.DEAD.value:
        stages.append(_stage("erro", "Discovery", last_discovery.last_error_message or "Falha"))
    elif last_discovery and last_discovery.status == JobStatus.SUCCESS.value:
        stages.append(
            _stage("ok", "Discovery", f"Última execução {_fmt(last_discovery.finished_at)}")
        )
    else:
        stages.append(_stage("atrasado", "Discovery", "Sem execução recente"))

    if sub_counts.get("ERROR", 0) or sub_counts.get("STALE", 0):
        stages.append(
            _stage(
                "warn" if not sub_counts.get("ERROR") else "erro",
                "Tracking / webhooks",
                f"ACTIVE={sub_counts['ACTIVE']} STALE={sub_counts['STALE']} "
                f"ERROR={sub_counts['ERROR']} · webhooks PENDING={pending_webhooks}",
                pending_webhooks,
            )
        )
    elif pending_webhooks > 20:
        stages.append(
            _stage(
                "atrasado",
                "Tracking / webhooks",
                f"Fila de webhooks alta ({pending_webhooks})",
                pending_webhooks,
            )
        )
    else:
        stages.append(
            _stage(
                "ok",
                "Tracking / webhooks",
                f"ACTIVE={sub_counts['ACTIVE']} · PENDING webhook={pending_webhooks}",
                pending_webhooks,
            )
        )

    if pending_events:
        stages.append(
            _stage(
                "em_andamento",
                "Eventos → digest",
                f"{pending_events} evento(s) aguardando digest",
                pending_events,
            )
        )
    else:
        stages.append(_stage("ok", "Eventos → digest", "Fila de notificação vazia", 0))

    if last_digest and last_digest.status == "FAILED":
        stages.append(_stage("erro", "Entrega e-mail", f"Último digest FAILED · {_fmt(last_digest.created_at)}"))
    elif last_digest and last_digest.status == "SENT":
        stages.append(
            _stage(
                "ok",
                "Entrega e-mail",
                f"Último enviado {_fmt(last_digest.sent_at)} → {settings.email_to or '—'}",
                last_digest.total_events,
            )
        )
    else:
        stages.append(
            _stage(
                "atrasado",
                "Entrega e-mail",
                f"Cursor digest: {_fmt(cursor.last_successful_digest_at if cursor else None)}",
            )
        )

    runs = list(session.scalars(select(Run).order_by(Run.created_at.desc()).limit(25)).all())
    run_rows = []
    for run in runs:
        jobs = list(
            session.scalars(select(Job).where(Job.run_id == run.id).order_by(Job.created_at)).all()
        )
        run_rows.append(
            {
                "id": run.id,
                "run_type": run.run_type,
                "trigger_type": run.trigger_type,
                "status": run.status,
                "run_mode": run.run_mode,
                "created_at": _fmt(run.created_at),
                "started_at": _fmt(run.started_at),
                "finished_at": _fmt(run.finished_at),
                "duration": _duration(run.started_at or run.created_at, run.finished_at),
                "error_summary": (run.error_summary or "")[:300],
                "jobs": [
                    {
                        "id": j.id,
                        "job_type": j.job_type,
                        "status": j.status,
                        "attempt_count": j.attempt_count,
                        "max_attempts": j.max_attempts,
                        "available_at": _fmt(j.available_at),
                        "last_error": (j.last_error_message or "")[:240],
                        **job_progress_dict(j),
                    }
                    for j in jobs
                ],
            }
        )

    dead = list(
        session.scalars(select(JobDeadLetter).order_by(JobDeadLetter.created_at.desc()).limit(20)).all()
    )
    subs = list(
        session.scalars(
            select(ProviderSubscription).order_by(ProviderSubscription.created_at.desc()).limit(40)
        ).all()
    )

    job_counts = {
        s: int(session.scalar(select(func.count()).select_from(Job).where(Job.status == s)) or 0)
        for s in (
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
            JobStatus.RETRY.value,
            JobStatus.DEAD.value,
            JobStatus.SUCCESS.value,
        )
    }

    live = build_progress_board(session)

    return {
        "stages": stages,
        "runs": run_rows,
        "dead_letters": [
            {
                "id": d.id,
                "job_id": d.job_id,
                "job_type": d.job_type,
                "error_code": d.error_code or "—",
                "error_message": (d.error_message or "")[:400],
                "created_at": _fmt(d.created_at),
            }
            for d in dead
        ],
        "subscriptions": [
            {
                "id": s.id,
                "tracking_type": s.tracking_type,
                "status": s.status,
                "external_tracking_id": s.external_tracking_id or "—",
                "last_webhook_at": _fmt(s.last_webhook_at),
                "next_expected_at": _fmt(s.next_expected_at),
            }
            for s in subs
        ],
        "job_counts": job_counts,
        "live": live,
        "refreshed_at": _fmt(utcnow()),
    }
