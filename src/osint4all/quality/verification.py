"""Motor de verificação: confirmado / provável / não confirmado / contestado / falso."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from osint4all.db.models import Entity, Investigation, VerificationRecord
from osint4all.db.repository import utcnow

VERDICTS = ("confirmed", "probable", "unconfirmed", "contested", "false")

VERDICT_LABELS = {
    "confirmed": "Confirmado",
    "probable": "Provável",
    "unconfirmed": "Não confirmado",
    "contested": "Contestado",
    "false": "Falso",
    "rejected": "Falso",
}

_CONFIDENCE = {
    "confirmed": 0.9,
    "probable": 0.65,
    "unconfirmed": 0.4,
    "contested": 0.35,
    "false": 0.05,
    "rejected": 0.05,
}


def verdict_label(verdict: str) -> str:
    return VERDICT_LABELS.get((verdict or "").strip().lower(), "Não confirmado")


def normalize_verdict(value: str) -> str:
    text = (value or "").strip().lower()
    if text == "rejected":
        return "false"
    return text if text in VERDICTS else "unconfirmed"


def apply_verdict(
    session: Session,
    investigation: Investigation,
    entity: Entity,
    *,
    verdict: str,
    reason: str,
    created_by: str | None,
) -> VerificationRecord:
    status = normalize_verdict(verdict)
    attrs = dict(entity.attrs or {})
    attrs["status"] = status
    attrs["motivo"] = (reason or "").strip()[:400] or verdict_label(status)
    entity.attrs = attrs
    entity.confidence = _CONFIDENCE[status]
    row = VerificationRecord(
        investigation_id=investigation.id,
        target_type="entity",
        target_id=entity.id,
        verdict=status,
        reason=attrs["motivo"],
        created_by=created_by,
        created_at=utcnow(),
    )
    session.add(row)
    return row


def latest_verdict(records: list[VerificationRecord], target_id: str) -> VerificationRecord | None:
    for row in reversed(records):
        if row.target_id == target_id:
            return row
    return None


def dossier_include(obj: Any) -> bool:
    from osint4all.graph.identity import entity_status

    return entity_status(obj) not in {"false", "rejected"}
