"""NATIONAL_RECONCILIATION — cobertura, lacunas e relações."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import Process, ProcessRelation, SourceRun
from monitor_jus.logging_setup import get_logger
from monitor_jus.pipeline.diary_sweep import run_diary_sweep
from monitor_jus.sources.datajud_router import resolve_process_source
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)


def run_national_reconciliation(
    session: Session,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    processes = list(session.scalars(select(Process)).all())
    courts: set[str] = set()
    segments: set[str] = set()
    for proc in processes:
        if proc.tribunal:
            courts.add(proc.tribunal.upper())
        parts = normalize_cnj(proc.numero_cnj)
        if parts:
            segments.add(parts.segmento)

    recent_runs = list(
        session.scalars(
            select(SourceRun).where(SourceRun.started_at >= cutoff)
        ).all()
    )
    covered_courts = {
        (r.court or "").upper()
        for r in recent_runs
        if r.status == "SUCCESS" and r.court
    }
    failed_sources = [
        {
            "job_type": r.job_type,
            "source": r.source,
            "court": r.court,
            "error": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in recent_runs
        if r.status == "FAILED"
    ]

    gap_courts = sorted(c for c in courts if c and c not in covered_courts)
    # sempre reconciliar destaque se sem cobertura recente
    for must in ("STF", "STJ", "TRF1"):
        if must not in covered_courts and must not in gap_courts:
            gap_courts.append(must)

    # Marcar processos sem rota DataJud
    flagged = 0
    superior_hits = 0
    for proc in processes:
        route = resolve_process_source(proc.numero_cnj, proc.tribunal, settings=settings)
        if route.requires_reconciliation or route.source == "DJEN_ONLY":
            proc.requires_reconciliation = True
            flagged += 1
        parts = normalize_cnj(proc.numero_cnj)
        if parts and parts.segmento in {"1", "3", "5"}:  # STF / STJ / trabalhistas superiores approx
            # segmento 3 = STJ; 1 = STF
            if parts.segmento in {"1", "3"}:
                superior_hits += 1

    rel_count = len(list(session.scalars(select(ProcessRelation)).all()))

    sweep_result: dict[str, Any] = {}
    if gap_courts:
        sweep_result = run_diary_sweep(
            session,
            settings=settings,
            gap_courts=gap_courts,
        )

    summary = {
        "processes": len(processes),
        "courts": sorted(courts),
        "segments": sorted(segments),
        "gap_courts": gap_courts,
        "failed_sources": failed_sources,
        "flagged_reconciliation": flagged,
        "superior_processes": superior_hits,
        "relations": rel_count,
        "sweep": sweep_result,
    }
    logger.info("national_reconciliation_done", extra={"extra": summary})
    return summary
