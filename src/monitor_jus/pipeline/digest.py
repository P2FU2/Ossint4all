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
from monitor_jus.report.pdf_report import write_pdf

logger = get_logger(__name__)


def _artifact_paths(settings: Settings, digest_id: str, reference_date: str | None) -> tuple[Path, Path]:
    stem = f"relatorio-{reference_date or digest_id[:8]}"
    base = Path(settings.outbox_dir)
    # Mantém id no nome para unicidade; stem amigável no anexo
    html_path = base / f"{digest_id}.html"
    pdf_path = base / f"{digest_id}.pdf"
    return html_path, pdf_path


def _ensure_pdf(html: str, pdf_path: Path) -> Path:
    return write_pdf(html, pdf_path)


def build_and_send_digest(
    session: Session,
    *,
    run_id: str | None = None,
    settings: Settings | None = None,
    digest_id: str | None = None,
    recipient: str | None = None,
) -> dict[str, Any]:
    """Cria digest (ou retenta o mesmo) e envia e-mail com HTML (sem PDF).

    `recipient` sobrescreve EMAIL_TO (envio sob demanda pelo painel).
    """
    settings = settings or get_settings()
    repo = Repository(session)

    if digest_id:
        report_progress(stage="digest_retry", done=0, total=2, message="Reenvio de digest", force=True)
        digest = repo.get_digest(digest_id)
        if not digest:
            raise PermanentJobError(f"Digest não encontrado: {digest_id}")
        html_path = Path(digest.html_path) if digest.html_path else None
        if not html_path or not html_path.exists():
            raise PermanentJobError("HTML do digest ausente para retry")
        html = html_path.read_text(encoding="utf-8")
        report_progress(stage="digest_retry", done=1, total=2, message="Enviando e-mail")
        return _deliver(
            session, repo, digest, html, settings, run_id, recipient=recipient
        )

    report_progress(stage="digest_load", done=0, total=5, message="Carregando eventos", force=True)
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
                total=5,
                message=f"Resumo IA {i + 1}/{len(events)}",
            )
            event.summary = summarize_event(session, event, settings)
        session.flush()
    else:
        report_progress(stage="digest_summaries", done=2, total=5, message="Sem eventos novos")

    report_progress(stage="digest_html", done=3, total=5, message="Gerando HTML")
    quarantine_count = repo.count_quarantine_open()
    from monitor_jus.report.html_report import recent_source_failures

    source_failures = recent_source_failures(session)
    html = render_digest_html(
        events,
        quarantine_count=quarantine_count,
        settings=settings,
        zero=not events,
        portfolio=portfolio,
        failures=[
            f"{f['source']}/{f['court']}: {f['error']}" for f in source_failures
        ],
    )
    html_path, pdf_path = _artifact_paths(settings, digest.id, digest.reference_date)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    digest.html_path = str(html_path)

    # PDF opcional só para arquivo local/histórico — não é anexo de e-mail
    report_progress(stage="digest_pdf", done=3.5, total=5, message="Arquivando PDF (histórico)")
    try:
        _ensure_pdf(html, pdf_path)
        digest.pdf_path = str(pdf_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("digest_pdf_skip", extra={"extra": {"err": str(exc)}})
        digest.pdf_path = None

    digest.generated_at = now
    digest.status = DigestStatus.READY.value
    digest.total_events = len(events)
    session.flush()

    incr("digest_events_total", float(len(events)))
    report_progress(stage="digest_send", done=4, total=5, message="Enviando e-mail")
    return _deliver(
        session,
        repo,
        digest,
        html,
        settings,
        run_id,
        portfolio=portfolio,
        recipient=recipient,
    )


def _deliver(
    session: Session,
    repo: Repository,
    digest: Any,
    html: str,
    settings: Settings,
    run_id: str | None,
    portfolio: dict[str, Any] | None = None,
    recipient: str | None = None,
) -> dict[str, Any]:
    digest.status = DigestStatus.DELIVERY_PENDING.value
    session.flush()
    subject_date = digest.reference_date or datetime.now().date().isoformat()
    total_proc = int((portfolio or {}).get("total_processes") or 0)
    subject = (
        f"[Monitor Judicial] Relatório {subject_date} — "
        f"{total_proc} processos · {digest.total_events} novidades"
    )

    html_file = Path(digest.html_path) if digest.html_path else None
    attach_name_base = f"monitor-judicial-{subject_date}"
    attachments: list[Path | dict[str, Any]] = []
    if html_file and html_file.is_file():
        attachments.append(
            {
                "filename": f"{attach_name_base}.html",
                "content": html_file.read_bytes(),
            }
        )
    else:
        attachments.append(
            {
                "filename": f"{attach_name_base}.html",
                "content": html.encode("utf-8"),
            }
        )

    note = (
        '<p style="font-size:13px;color:#555;margin:12px 0 0">'
        "Anexo neste e-mail: relatório em <strong>HTML</strong> "
        "com as mesmas informações do corpo."
        "</p>"
    )
    if "</body>" in html.lower():
        # inserção case-insensitive simples
        idx = html.lower().rfind("</body>")
        html_with_note = html[:idx] + note + html[idx:]
    else:
        html_with_note = html + note

    to_addr = (recipient or "").strip() or settings.email_to
    notification = repo.create_notification(
        run_id=run_id,
        digest_id=digest.id,
        recipient=to_addr,
        status="PENDING",
        html_path=digest.html_path,
    )
    try:
        result = send_html_email(
            subject=subject,
            html=html_with_note,
            settings=settings,
            outbox_path=html_file,
            attachments=attachments,
            to=to_addr,
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
        report_progress(
            stage="digest_send",
            done=5,
            total=5,
            message=f"E-mail enviado com {result.get('attachments', 0)} anexo(s)",
            force=True,
        )
        return {
            "digest_id": digest.id,
            "status": "SENT",
            "total_events": digest.total_events,
            "total_processes": total_proc,
            "message_id": result.get("message_id"),
            "attachments": result.get("attachments", 0),
            "html_path": digest.html_path,
            "pdf_path": digest.pdf_path,
            "recipient": to_addr,
        }
    except Exception as exc:  # noqa: BLE001
        notification.status = "FAILED"
        session.flush()
        report_progress(stage="digest_send", message=f"Falha no envio: {exc}", force=True)
        logger.error("digest_delivery_failed", extra={"extra": {"err": str(exc)}})
        raise RecoverableJobError(str(exc), code="DELIVERY_FAILED") from exc
