"""Histórico de digests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings
from monitor_jus.db.models import Digest, DigestItem, Event, Notification
from monitor_jus.security import redact_text


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


def list_digests(session: Session) -> dict[str, Any]:
    digests = list(session.scalars(select(Digest).order_by(Digest.created_at.desc()).limit(100)).all())
    rows = []
    for d in digests:
        notif = session.scalar(
            select(Notification)
            .where(Notification.digest_id == d.id)
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        rows.append(
            {
                "id": d.id,
                "reference_date": d.reference_date or "—",
                "status": d.status,
                "total_events": d.total_events,
                "window_start": _fmt(d.window_start),
                "window_end": _fmt(d.window_end),
                "generated_at": _fmt(d.generated_at),
                "sent_at": _fmt(d.sent_at),
                "recipient": notif.recipient if notif else "—",
                "provider_message_id": (notif.provider_message_id if notif else None) or "—",
                "notification_status": notif.status if notif else "—",
                "html_path": d.html_path,
            }
        )
    return {"digests": rows, "total": len(rows)}


def get_digest_detail(session: Session, digest_id: str, settings: Settings) -> dict[str, Any] | None:
    d = session.get(Digest, digest_id)
    if not d:
        return None
    items = list(session.scalars(select(DigestItem).where(DigestItem.digest_id == d.id)).all())
    events = []
    for item in items:
        e = session.get(Event, item.event_id)
        if not e:
            continue
        events.append(
            {
                "id": e.id,
                "event_type": e.event_type,
                "title": e.title or e.event_type,
                "summary": redact_text(e.summary or e.description or ""),
                "priority": e.priority,
                "numero_cnj": e.numero_cnj or "—",
                "notify_status": e.notify_status,
                "official_link": e.official_link,
                "created_at": _fmt(e.created_at),
            }
        )
    notifications = list(
        session.scalars(select(Notification).where(Notification.digest_id == d.id)).all()
    )
    html_exists = False
    if d.html_path:
        html_exists = Path(d.html_path).is_file()

    return {
        "id": d.id,
        "reference_date": d.reference_date or "—",
        "status": d.status,
        "total_events": d.total_events,
        "window_start": _fmt(d.window_start),
        "window_end": _fmt(d.window_end),
        "generated_at": _fmt(d.generated_at),
        "sent_at": _fmt(d.sent_at),
        "html_path": d.html_path,
        "html_exists": html_exists,
        "events": events,
        "notifications": [
            {
                "id": n.id,
                "recipient": n.recipient,
                "status": n.status,
                "provider_message_id": n.provider_message_id or "—",
                "sent_at": _fmt(n.sent_at),
            }
            for n in notifications
        ],
        "email_to": settings.email_to or "—",
    }
