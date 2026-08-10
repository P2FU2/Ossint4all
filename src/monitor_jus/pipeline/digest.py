"""Digest diário — só novidades; reserva recuperável até confirmação de envio."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from monitor_jus.ai.summarizer import summarize_event
from monitor_jus.config import Settings, get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import PermanentJobError, RecoverableJobError
from monitor_jus.logging_setup import get_logger
from monitor_jus.mail.resend_mailer import send_html_email
from monitor_jus.metrics import incr, set_gauge
from monitor_jus.models import DigestStatus
from monitor_jus.progress import report as report_progress
from monitor_jus.report.html_report import render_digest_html
from monitor_jus.report.pdf_report import write_pdf

logger = get_logger(__name__)


def _local_now(settings: Settings) -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.tz))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def _artifact_paths(settings: Settings, digest_id: str, reference_date: str | None) -> tuple[Path, Path]:
    base = Path(settings.outbox_dir)
    html_path = base / f"{digest_id}.html"
    pdf_path = base / f"{digest_id}.pdf"
    return html_path, pdf_path


def _ensure_pdf(html: str, pdf_path: Path) -> Path:
    return write_pdf(html, pdf_path)


def _format_subject_date(reference_date: str | None, *, settings: Settings | None = None) -> str:
    if reference_date:
        raw = reference_date
    elif settings is not None:
        raw = _local_now(settings).date().isoformat()
    else:
        raw = datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _digest_subject(
    reference_date: str | None,
    total_events: int,
    *,
    settings: Settings | None = None,
) -> str:
    day = _format_subject_date(reference_date, settings=settings)
    if total_events <= 0:
        return f"[Monitor Judicial] Relatório {day} — nenhuma novidade"
    return f"[Monitor Judicial] Relatório {day} — {total_events} novidades"


def _should_email_empty(
    *,
    failure_lines: list[str],
    source_health: dict[str, Any] | None,
) -> bool:
    """E-mail vazio só se houver aviso útil de cobertura/fonte."""
    if failure_lines:
        return True
    if source_health and source_health.get("has_issues"):
        return True
    return False


def build_and_send_digest(
    session: Session,
    *,
    run_id: str | None = None,
    settings: Settings | None = None,
    digest_id: str | None = None,
    recipient: str | None = None,
) -> dict[str, Any]:
    """Reserva eventos → HTML só novidades → send → NOTIFIED; falha → DELIVERY_PENDING."""
    settings = settings or get_settings()
    repo = Repository(session)

    if digest_id:
        report_progress(stage="digest_retry", done=0, total=2, message="Reenvio de digest", force=True)
        digest = repo.get_digest(digest_id)
        if not digest:
            raise PermanentJobError(f"Digest não encontrado: {digest_id}")
        if digest.status == DigestStatus.SENT.value:
            return {
                "digest_id": digest.id,
                "status": "SENT",
                "total_events": digest.total_events,
                "skipped": "already_sent",
            }
        if digest.status not in (
            DigestStatus.READY.value,
            DigestStatus.DELIVERY_PENDING.value,
        ):
            raise PermanentJobError(
                f"Digest {digest_id} não está pronto para envio ({digest.status})"
            )
        html_path = Path(digest.html_path) if digest.html_path else None
        if not html_path or not html_path.exists():
            raise PermanentJobError("HTML do digest ausente para retry")
        html = html_path.read_text(encoding="utf-8")
        report_progress(stage="digest_retry", done=1, total=2, message="Enviando e-mail")
        return _deliver(
            session, repo, digest, html, settings, run_id, recipient=recipient
        )

    # Retry de digest aberto (READY / DELIVERY_PENDING) — não cria digest B
    open_digest = repo.find_open_delivery_digest()
    if open_digest:
        html_path = Path(open_digest.html_path) if open_digest.html_path else None
        if html_path and html_path.exists():
            report_progress(
                stage="digest_retry_open",
                done=0,
                total=2,
                message="Reenviando digest pendente",
                force=True,
            )
            html = html_path.read_text(encoding="utf-8")
            return _deliver(
                session,
                repo,
                open_digest,
                html,
                settings,
                run_id,
                recipient=recipient,
            )
        # HTML ausente: libera reserva e segue (evita flood de digests vazios)
        released = repo.release_digest_reservation(
            open_digest, reason="html_missing_reclaim"
        )
        logger.warning(
            "digest_open_reclaimed",
            extra={"extra": {"digest_id": open_digest.id, "released": released}},
        )

    # Crash mid-build: libera IN_DIGEST órfãos antes de montar o próximo
    building = repo.find_building_digest()
    if building:
        released = repo.release_digest_reservation(building, reason="building_reclaim")
        logger.warning(
            "digest_building_reclaimed",
            extra={"extra": {"digest_id": building.id, "released": released}},
        )

    report_progress(stage="digest_load", done=0, total=5, message="Carregando eventos", force=True)
    cursor = repo.get_digest_cursor()
    since = cursor.last_successful_digest_at
    # Status PENDING_NOTIFY é a fonte da verdade — cursor só como metadado da janela
    events = repo.pending_notify_events()
    now = datetime.now(timezone.utc)
    local = _local_now(settings)

    digest = repo.create_digest(
        reference_date=local.date().isoformat(),
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
    from monitor_jus.report.html_report import (
        format_source_failures_for_user,
        recent_source_failures,
    )
    from monitor_jus.web.services.coverage_health import digest_source_health

    source_failures = recent_source_failures(session)
    source_health = digest_source_health(session)
    failure_lines = format_source_failures_for_user(source_failures)
    html = render_digest_html(
        events,
        quarantine_count=quarantine_count,
        settings=settings,
        zero=not events,
        failures=failure_lines,
        source_health=source_health,
    )
    html_path, pdf_path = _artifact_paths(settings, digest.id, digest.reference_date)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    digest.html_path = str(html_path)

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

    # Sem novidades e sem alerta de cobertura → arquiva e não manda e-mail
    if not events and not _should_email_empty(
        failure_lines=failure_lines, source_health=source_health
    ):
        repo.mark_digest_sent(digest)
        report_progress(
            stage="digest_send",
            done=5,
            total=5,
            message="Sem novidades — e-mail omitido",
            force=True,
        )
        return {
            "digest_id": digest.id,
            "status": "SKIPPED_EMPTY",
            "total_events": 0,
            "html_path": digest.html_path,
            "pdf_path": digest.pdf_path,
        }

    report_progress(stage="digest_send", done=4, total=5, message="Enviando e-mail")
    return _deliver(
        session,
        repo,
        digest,
        html,
        settings,
        run_id,
        recipient=recipient,
    )


def _deliver(
    session: Session,
    repo: Repository,
    digest: Any,
    html: str,
    settings: Settings,
    run_id: str | None,
    recipient: str | None = None,
) -> dict[str, Any]:
    if digest.status == DigestStatus.SENT.value:
        return {
            "digest_id": digest.id,
            "status": "SENT",
            "total_events": digest.total_events,
            "skipped": "already_sent",
        }
    digest.status = DigestStatus.DELIVERY_PENDING.value
    session.flush()
    subject = _digest_subject(
        digest.reference_date,
        int(digest.total_events or 0),
        settings=settings,
    )
    subject_date = digest.reference_date or _local_now(settings).date().isoformat()

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
        # Não sobrescrever o HTML canônico do outbox com a nota do corpo
        result = send_html_email(
            subject=subject,
            html=html_with_note,
            settings=settings,
            outbox_path=None,
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
            "message_id": result.get("message_id"),
            "attachments": result.get("attachments", 0),
            "html_path": digest.html_path,
            "pdf_path": digest.pdf_path,
            "recipient": to_addr,
            "subject": subject,
        }
    except Exception as exc:  # noqa: BLE001
        # Mantém DELIVERY_PENDING + itens IN_DIGEST para retry do mesmo digest
        notification.status = "FAILED"
        digest.status = DigestStatus.DELIVERY_PENDING.value
        session.flush()
        report_progress(stage="digest_send", message=f"Falha no envio: {exc}", force=True)
        logger.error("digest_delivery_failed", extra={"extra": {"err": str(exc), "digest_id": digest.id}})
        raise RecoverableJobError(str(exc), code="DELIVERY_FAILED") from exc
