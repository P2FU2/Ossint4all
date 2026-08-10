"""Agregados do dashboard."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings
from monitor_jus.db.models import (
    BootstrapState,
    Digest,
    Event,
    EventQuarantine,
    Job,
    JobDeadLetter,
    Notification,
    User,
    WebhookRaw,
)
from monitor_jus.db.repository import utcnow
from monitor_jus.models import DigestStatus, JobStatus, NotifyStatus, Priority
from monitor_jus.pipeline.portfolio import build_portfolio_stats
from monitor_jus.web.services.progress_board import build_progress_board


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


_DIGEST_STATUS_LABELS = {
    DigestStatus.BUILDING.value: "Gerando",
    DigestStatus.READY.value: "Pronto",
    DigestStatus.DELIVERY_PENDING.value: "Aguardando envio",
    DigestStatus.SENT.value: "Enviado",
    DigestStatus.PARTIAL.value: "Parcial",
    DigestStatus.FAILED.value: "Falhou",
}


def _digest_status_label(status: str | None) -> str:
    if not status:
        return "—"
    return _DIGEST_STATUS_LABELS.get(status, status)


def build_dashboard(
    session: Session,
    settings: Settings,
    *,
    user: User | None = None,
) -> dict[str, Any]:
    # Stats leves — sem lista completa / sem payload JSON
    portfolio = build_portfolio_stats(session)
    is_admin = bool(user and user.role == "admin")

    pending_notify = int(
        session.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.notify_status == NotifyStatus.PENDING_NOTIFY.value)
        )
        or 0
    )
    urgent_pending = int(
        session.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.notify_status == NotifyStatus.PENDING_NOTIFY.value,
                Event.priority == Priority.ALTA.value,
            )
        )
        or 0
    )

    last_digest = session.scalar(select(Digest).order_by(Digest.created_at.desc()).limit(1))
    last_notification = None
    if last_digest:
        last_notification = session.scalar(
            select(Notification)
            .where(Notification.digest_id == last_digest.id)
            .order_by(Notification.created_at.desc())
            .limit(1)
        )

    bootstrap = session.get(BootstrapState, 1)

    recent_events = list(
        session.scalars(select(Event).order_by(Event.created_at.desc()).limit(8)).all()
    )

    # Operacional só para admin (evita queries extras no viewer)
    job_counts = {
        JobStatus.PENDING.value: 0,
        JobStatus.RUNNING.value: 0,
        JobStatus.DEAD.value: 0,
        JobStatus.RETRY.value: 0,
    }
    attention: list[dict[str, str]] = []
    live: dict[str, Any] = {
        "headline": None,
        "active_count": 0,
        "running_count": 0,
        "pending_count": 0,
    }
    health = {
        "djen_enabled": bool(settings.djen_enable),
        "cna_enabled": bool(settings.cna_enabled),
        "email_to": settings.email_to or "—",
        "openrouter": bool(settings.openrouter_api_key),
        "datajud": bool(settings.datajud_enable and settings.datajud_api_key),
    }

    if is_admin:
        job_counts = {
            status: int(
                session.scalar(select(func.count()).select_from(Job).where(Job.status == status))
                or 0
            )
            for status in (
                JobStatus.PENDING.value,
                JobStatus.RUNNING.value,
                JobStatus.DEAD.value,
                JobStatus.RETRY.value,
            )
        }
        quarantine_open = int(
            session.scalar(
                select(func.count())
                .select_from(EventQuarantine)
                .where(EventQuarantine.resolved_at.is_(None))
            )
            or 0
        )
        dead_letters = int(session.scalar(select(func.count()).select_from(JobDeadLetter)) or 0)
        stale_cutoff = utcnow() - timedelta(hours=6)
        stale_webhooks = int(
            session.scalar(
                select(func.count())
                .select_from(WebhookRaw)
                .where(WebhookRaw.status == "PENDING", WebhookRaw.received_at < stale_cutoff)
            )
            or 0
        )
        live = build_progress_board(session)

        if quarantine_open:
            attention.append(
                {"level": "warn", "text": f"{quarantine_open} item(ns) em quarentena aberta"}
            )
        if dead_letters:
            if bootstrap and bootstrap.completed:
                attention.append(
                    {
                        "level": "warn",
                        "text": (
                            f"{dead_letters} job(s) em dead letter — "
                            "há bootstrap concluído depois; pode ser falha antiga"
                        ),
                    }
                )
            else:
                attention.append(
                    {"level": "error", "text": f"{dead_letters} job(s) em dead letter"}
                )
        if last_digest and last_digest.status == DigestStatus.FAILED.value:
            attention.append({"level": "error", "text": "Último e-mail falhou"})
        if stale_webhooks:
            attention.append(
                {"level": "warn", "text": f"{stale_webhooks} webhook(s) PENDING há mais de 6h"}
            )
        if bootstrap and not bootstrap.completed:
            attention.append(
                {"level": "warn", "text": "Leitura inicial do acervo ainda não concluída"}
            )
        if live.get("running_count", 0) > 1:
            attention.append(
                {
                    "level": "warn",
                    "text": (
                        f"{live['running_count']} jobs RUNNING juntos — "
                        "verifique se há mais de 1 réplica de worker"
                    ),
                }
            )
        from monitor_jus.web.services.coverage_health import coverage_attention

        attention.extend(
            coverage_attention(session, djen_enabled=bool(settings.djen_enable))
        )
        if not attention:
            attention.append({"level": "ok", "text": "Nenhum alerta operacional no momento"})

    return {
        "portfolio": portfolio,
        "pending_notify": pending_notify,
        "urgent_pending": urgent_pending,
        "last_digest": {
            "id": last_digest.id if last_digest else None,
            "status": _digest_status_label(last_digest.status if last_digest else None),
            "status_raw": last_digest.status if last_digest else None,
            "reference_date": last_digest.reference_date if last_digest else "—",
            "total_events": last_digest.total_events if last_digest else 0,
            "sent_at": _fmt(last_digest.sent_at if last_digest else None),
            "generated_at": _fmt(last_digest.generated_at if last_digest else None),
            "recipient": last_notification.recipient if last_notification else settings.email_to or "—",
        },
        "bootstrap": {
            "completed": bool(bootstrap and bootstrap.completed),
            "baseline_at": _fmt(bootstrap.baseline_at if bootstrap else None),
        },
        "job_counts": job_counts,
        "attention": attention,
        "live": live,
        "recent_events": [
            {
                "id": e.id,
                "title": e.title or e.event_type,
                "summary": (e.summary or e.description or "")[:180],
                "priority": e.priority,
                "numero_cnj": e.numero_cnj or "—",
                "notify_status": e.notify_status,
                "created_at": _fmt(e.created_at),
            }
            for e in recent_events
        ],
        "health": health,
        "default_email_to": settings.email_to or "",
    }
