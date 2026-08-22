"""Saúde das fontes: config, falha recente e latência do health()."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.connectors.registry import build_connectors
from osint4all.db.models import ExpansionJob, SourceHealthCheck
from osint4all.db.repository import utcnow


def probe_sources(session: Session) -> list[SourceHealthCheck]:
    rows: list[SourceHealthCheck] = []
    for connector in build_connectors():
        started = time.perf_counter()
        error = ""
        detail: dict[str, Any] = {}
        ok = True
        try:
            detail = connector.health() or {}
            enabled = bool(detail.get("enabled", True))
            if not enabled:
                ok = True
                error = "desligada"
            elif detail.get("paid_only") and detail.get("api_key_configured") is False:
                ok = True
                error = "paga (não usada)"
            elif detail.get("api_key_configured") is False and not detail.get("free_fallback"):
                ok = True
                error = "alternativa gratuita"
            else:
                ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            error = str(exc)[:400]
        latency = int((time.perf_counter() - started) * 1000)
        row = SourceHealthCheck(
            connector=connector.name,
            ok=ok,
            latency_ms=latency,
            error=error,
            detail=detail,
            checked_at=utcnow(),
        )
        session.add(row)
        rows.append(row)
    return rows


def latest_health(session: Session) -> dict[str, SourceHealthCheck]:
    rows = session.scalars(select(SourceHealthCheck).order_by(SourceHealthCheck.checked_at.desc()).limit(80)).all()
    out: dict[str, SourceHealthCheck] = {}
    for row in rows:
        out.setdefault(row.connector, row)
    return out


def recent_job_errors(session: Session, investigation_id: str, *, limit: int = 8) -> list[ExpansionJob]:
    return list(
        session.scalars(
            select(ExpansionJob)
            .where(ExpansionJob.investigation_id == investigation_id, ExpansionJob.status == "FAILED")
            .order_by(ExpansionJob.finished_at.desc())
            .limit(limit)
        ).all()
    )
