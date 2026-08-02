"""Ações administrativas do painel (enqueue)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from email_validator import EmailNotValidError, validate_email

from monitor_jus.config import Settings
from monitor_jus.db.models import Job, Run
from monitor_jus.db.repository import Repository, utcnow
from monitor_jus.mail.resend_mailer import parse_recipients
from monitor_jus.models import JobStatus, RunMode, RunStatus, RunType
from monitor_jus.web.auth import write_audit

ALLOWED_RUN_TYPES = {
    RunType.DAILY_DIGEST.value,
    RunType.BOOTSTRAP.value,
    RunType.HISTORICAL_DISCOVERY.value,
    RunType.RECONCILIATION.value,
    RunType.DELIVERY_RETRY.value,
    RunType.PROCESS_REFRESH.value,
}

# Jobs pesados que não devem sobrepor discovery/bootstrap
_HEAVY_JOB_TYPES = {"BOOTSTRAP", "HISTORICAL_DISCOVERY"}
_HEAVY_RUN_TYPES = {RunType.BOOTSTRAP.value, RunType.HISTORICAL_DISCOVERY.value}
_ACTIVE = (JobStatus.PENDING.value, JobStatus.RUNNING.value, JobStatus.RETRY.value)


def _cancel_job(session: Session, job: Job, reason: str) -> None:
    now = utcnow()
    job.status = JobStatus.CANCELLED.value
    job.last_error_message = reason[:512]
    job.finished_at = now
    job.locked_by = None
    job.progress_stage = "cancelled"
    if not job.progress_message:
        job.progress_message = reason[:512]
    if job.run_id:
        run = session.get(Run, job.run_id)
        if run and run.status in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
            run.status = RunStatus.CANCELLED.value
            run.finished_at = now
            run.error_summary = reason[:512]


def cancel_stale_pending_jobs(
    session: Session,
    *,
    hours: float = 2.0,
    job_types: set[str] | None = None,
) -> int:
    """Cancela jobs PENDING antigos (fila suja) sem heartbeat/início."""
    types = job_types or _HEAVY_JOB_TYPES
    cutoff = utcnow() - timedelta(hours=hours)
    stale = list(
        session.scalars(
            select(Job).where(
                Job.status == JobStatus.PENDING.value,
                Job.job_type.in_(types),
                Job.created_at < cutoff,
                Job.started_at.is_(None),
            )
        ).all()
    )
    for job in stale:
        _cancel_job(session, job, "Cancelado automaticamente: PENDING antigo (fila suja)")
    if stale:
        session.flush()
    return len(stale)


def reap_stale_running_jobs(
    session: Session,
    *,
    heartbeat_minutes: float = 30.0,
    never_started_minutes: float = 20.0,
) -> int:
    """
    Marca RUNNING sem heartbeat como CANCELLED (worker morto/redeploy).

    Discovery pode durar horas — só ceifa se o heartbeat parou.
    Jobs em 0% sem nenhuma atualização caem mais cedo (never_started).
    """
    now = utcnow()
    hb_cutoff = now - timedelta(minutes=heartbeat_minutes)
    never_cutoff = now - timedelta(minutes=never_started_minutes)
    running = list(
        session.scalars(select(Job).where(Job.status == JobStatus.RUNNING.value)).all()
    )
    reaped = 0
    for job in running:
        hb = job.heartbeat_at or job.started_at or job.created_at
        if not hb:
            continue
        pct = int(job.progress_pct or 0)
        stage = (job.progress_stage or "").strip().lower()
        never_progressed = pct <= 0 and stage in ("", "starting", "—", "-")
        if never_progressed and hb < never_cutoff:
            _cancel_job(
                session,
                job,
                (
                    "Cancelado: RUNNING sem progresso/heartbeat "
                    f"(>{never_started_minutes:.0f} min) — worker provavelmente reiniciou"
                ),
            )
            reaped += 1
            continue
        if hb < hb_cutoff:
            _cancel_job(
                session,
                job,
                (
                    "Cancelado: heartbeat expirado "
                    f"(>{heartbeat_minutes:.0f} min sem atualização) — worker morto/redeploy"
                ),
            )
            reaped += 1
    if reaped:
        session.flush()
    return reaped


def cleanup_stale_jobs(session: Session) -> dict[str, int]:
    """Limpa PENDING antigos + RUNNING zumbis. Seguro chamar a cada refresh da UI."""
    pending = cancel_stale_pending_jobs(session, hours=2.0)
    running = reap_stale_running_jobs(session)
    if pending or running:
        session.flush()
    return {"pending_cancelled": pending, "running_reaped": running}


def _active_heavy_jobs(session: Session) -> list[Job]:
    return list(
        session.scalars(
            select(Job)
            .where(
                Job.job_type.in_(_HEAVY_JOB_TYPES),
                Job.status.in_(_ACTIVE),
            )
            .order_by(Job.created_at.desc())
            .limit(10)
        ).all()
    )


def assert_heavy_job_allowed(session: Session, run_type: str) -> None:
    """Bloqueia bootstrap/discovery sobrepostos."""
    if run_type not in _HEAVY_RUN_TYPES:
        return
    active = _active_heavy_jobs(session)
    if active:
        sample = ", ".join(f"{j.job_type}({j.status})" for j in active[:3])
        raise ValueError(
            "Já existe discovery/bootstrap em andamento ou na fila "
            f"({sample}). Aguarde a conclusão antes de disparar outro."
        )


def normalize_email_to(raw: str) -> str:
    """Valida e normaliza um ou mais e-mails (separados por vírgula)."""
    parts = parse_recipients(raw)
    if not parts:
        raise ValueError("Informe ao menos um e-mail de destino")
    cleaned: list[str] = []
    for part in parts:
        try:
            info = validate_email(part, check_deliverability=False)
            cleaned.append(info.normalized)
        except EmailNotValidError as exc:
            raise ValueError(f"E-mail inválido ({part}): {exc}") from exc
    return ",".join(cleaned)


def enqueue_from_ui(
    session: Session,
    settings: Settings,
    *,
    run_type: str,
    username: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    if run_type not in ALLOWED_RUN_TYPES:
        raise ValueError(f"run_type não permitido: {run_type}")

    # Limpa fila suja / zumbis antes de enfileirar
    cleanup_stale_jobs(session)
    assert_heavy_job_allowed(session, run_type)

    repo = Repository(session)
    idem = f"ui:{run_type}:{uuid4().hex[:12]}"
    run = repo.create_run(
        run_type,
        trigger_type="ui",
        run_mode=RunMode.LIVE.value,
        idempotency_key=idem,
    )
    job_type = run_type
    if run_type == RunType.BOOTSTRAP.value:
        job_type = "BOOTSTRAP"
    repo.enqueue_job(
        run.id,
        job_type,
        payload=payload or {},
        max_attempts=settings.job_max_attempts,
        idempotency_key=f"job:{idem}",
    )
    write_audit(
        session,
        "run.enqueue",
        username=username,
        details={"run_type": run_type, "run_id": run.id, "payload": payload or {}},
    )
    return {"run_id": run.id, "status": "accepted"}


def enqueue_report_email(
    session: Session,
    settings: Settings,
    *,
    username: str,
    email_to: str,
) -> dict[str, str]:
    """Enfileira relatório (mesmo fluxo do digest) para o(s) e-mail(s) informado(s)."""
    normalized = normalize_email_to(email_to)
    return enqueue_from_ui(
        session,
        settings,
        run_type=RunType.DAILY_DIGEST.value,
        username=username,
        payload={"email_to": normalized, "source": "ui_send_report"},
    )
