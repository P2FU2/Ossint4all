"""Helpers de quarentena de eventos."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from monitor_jus.db.repository import Repository
from monitor_jus.metrics import incr
from monitor_jus.models import QuarantineReason


def quarantine_event(
    session: Session,
    reason: QuarantineReason | str,
    payload: dict[str, Any] | None,
    *,
    details: str | None = None,
    delivery_key: str | None = None,
) -> None:
    repo = Repository(session)
    repo.quarantine(
        reason=str(reason),
        payload=payload,
        details=details,
        delivery_key=delivery_key,
    )
    incr("events_quarantined")
