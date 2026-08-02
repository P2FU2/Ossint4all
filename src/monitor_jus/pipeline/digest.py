"""Digest diário transacional."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from monitor_jus.ai.summarizer import summarize_event
from monitor_jus.config import Settings, get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import PermanentJobError, RecoverableJobError
from monitor_jus.logging_setup import get_logger
from monitor_jus.mail.resend_mailer import send_html_email
from monitor_jus.metrics import incr, set_gauge
from monitor_jus.models import DigestStatus
from monitor_jus.pipeline.portfolio import build_portfolio
from monitor_jus.progress import report as report_progress
from monitor_jus.report.html_report import render_digest_html

logger = get_logger(__name__)


def build_and_send_digest(
    session: Session,
    *,
    run_id: str | None = None,
    settings: Settings | None = None,
    digest_id: str | None = None,
) -> dict[str, Any]:
    """Cria digest (ou retenta o mesmo) e envia e-mail."""
    settings = settings or get_settings()
    repo = Repository(session)

    if digest_id:
        report_progress(stage="digest_retry", done=0, total=2, message="Reenvio de digest", force=True)
        digest = repo.get_digest(digest_id)
        if not digest:
            raise PermanentJobError(f"Digest não encontrado: {digest_id}")
        # retry delivery
        html_path = Path(digest.html_path) if digest.html_path else None
        if not html_path or not html_path.exists():
            raise PermanentJobError("HTML do digest ausente para retry")
        html = html_path.read_text(encoding="utf-8")
        report_progress(stage="digest_retry", done=1, total=2, message="Enviando e-mail")
        return _deliver(session, repo, digest, html, settings, run_id)

    report_progress(stage="digest_load", done=0, total=4, message="Carregando eventos", force=True)
    cursor = repo.get_digest_cursor()
    since = cursor.last_successful_digest_at
    events = repo.pending_notify_events(since)
    now = datetime.now(timezone.utc)
    portfolio = build_portfolio(session)

    digest = repo.create_digest(
        reference_date=now.date().isoformat(),
        window_start=since,
        window_end=now,
        status=DigestStatus.BUILDING.value,
        run_id=run_id,
        total_events=len(events),
    )

    if events:
        repo.attach_digest_items(digest.id, [e.id for e in events])
        n_ev = max(len(events), 1)
        for i, event in enumerate(events):
            report_progress(
                stage="digest_summaries",
                done=1 + (i / n_ev),
                total=4,
                message=f"Resumo IA {i + 1}/{len(events)}",
            )
            event.summary = summarize_event(session, event, settings)
        session.flush()
    else:
        report_progress(stage="digest_summaries", done=2, total=4, message="Sem eventos novos")

    report_progress(stage="digest_html", done=3, total=4, message="Gerando HTML")
    quarantine_count = repo.count_quarantine_open()
    html = render_digest_html(
        events,
        quarantine_count=quarantine_count,
        settings=settings,
        zero=not events,
        portfolio=portfolio,
    )
    outbox = Path(settings.outbox_dir) / f"{digest.id}.html"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    outbox.write_text(html, encoding="utf-8")
    digest.html_path = str(outbox)
    digest.generated_at = now
    digest.status = DigestStatus.READY.value
    digest.total_events = len(events)
    session.flush()

    incr("digest_events_total", float(len(events)))
    report_progress(stage="digest_send", done=3.5, total=4, message="Enviando e-mail")
    return _deliver(session, repo, digest, html, settings, run_id, portfolio=portfolio)


def _deliver(
    session: Session,
    repo: Repository,
    digest: Any,
    html: str,
    settings: Settings,
    run_id: str | None,
    portfolio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    digest.status = DigestStatus.DELIVERY_PENDING.value
    session.flush()
    subject_date = digest.reference_date or datetime.now().date().isoformat()
    total_proc = int((portfolio or {}).get("total_processes") or 0)
    subject = (
        f"[Monitor Judicial] Relatório {subject_date} — "
        f"{total_proc} processos · {digest.total_events} novidades"
    )
    notification = repo.create_notification(
        run_id=run_id,
        digest_id=digest.id,
        recipient=settings.email_to,
        status="PENDING",
        html_path=digest.html_path,
    )
    try:
        result = send_html_email(
            subject=subject,
            html=html,
            settings=settings,
            outbox_path=Path(digest.html_path) if digest.html_path else None,
        )
        notification.status = "SENT"
        notification.provider_message_id = result.get("message_id")
        notification.sent_at = datetime.now(timezone.utc)
        repo.mark_digest_sent(digest)
        set_gauge(
            "last_successful_digest_timestamp",
            datetime.now(timezone.utc).timestamp(),
        )
        session.flush()
        report_progress(stage="digest_send", done=4, total=4, message="E-mail enviado", force=True)
        return {
            "digest_id": digest.id,
            "status": "SENT",
            "total_events": digest.total_events,
            "total_processes": total_proc,
            "message_id": result.get("message_id"),
        }
    except Exception as exc:  # noqa: BLE001
        notification.status = "FAILED"
        session.flush()
        report_progress(stage="digest_send", message=f"Falha no envio: {exc}", force=True)
        logger.error("digest_delivery_failed", extra={"extra": {"err": str(exc)}})
        # eventos permanecem IN_DIGEST
        raise RecoverableJobError(str(exc), code="DELIVERY_FAILED") from exc
