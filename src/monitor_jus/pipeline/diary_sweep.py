"""DIARY_SWEEP — varredura complementar por tribunal (não nacional completa)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_cobertura
from monitor_jus.db.models import Process
from monitor_jus.logging_setup import get_logger
from monitor_jus.pipeline.communication_ingest import (
    finish_source_run,
    ingest,
    start_source_run,
)
from monitor_jus.progress import report as report_progress
from monitor_jus.sources.djen.client import DjenClient
from monitor_jus.sources.djen.criteria import DjenSearchCriteria

logger = get_logger(__name__)


def courts_to_sweep(
    session: Session,
    settings: Settings,
    *,
    gap_courts: list[str] | None = None,
) -> list[str]:
    cobertura = load_cobertura(settings)
    highlight = [str(c).upper() for c in (cobertura.get("tribunais_destaque") or ["STF", "STJ", "TRF1"])]
    active = [str(c).upper() for c in (cobertura.get("tribunais_ativos") or []) if c]

    portfolio_courts: set[str] = set()
    for row in session.scalars(select(Process)).all():
        if row.tribunal:
            portfolio_courts.add(row.tribunal.strip().upper())

    if active:
        courts = set(active) | set(highlight) | portfolio_courts
    else:
        # vazio = não varrer o país inteiro; só acervo + destaque
        courts = portfolio_courts | set(highlight) | {"STF", "STJ", "TRF1"}

    if gap_courts:
        courts |= {c.upper() for c in gap_courts}

    return sorted(c for c in courts if c)


def run_diary_sweep(
    session: Session,
    settings: Settings | None = None,
    *,
    bootstrap_mode: bool = False,
    gap_courts: list[str] | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.djen_enable:
        return {"status": "skipped", "reason": "djen_disabled"}

    client = DjenClient(settings)
    courts = courts_to_sweep(session, settings, gap_courts=gap_courts)
    until = date.today()
    start = until - timedelta(days=2)

    report_progress(
        stage="diary_sweep",
        done=0,
        total=max(len(courts), 1),
        message=f"DIARY_SWEEP · {len(courts)} tribunal(is)",
        force=True,
    )

    results: list[dict[str, Any]] = []
    for idx, court in enumerate(courts):
        report_progress(
            stage="diary_sweep",
            done=idx,
            total=max(len(courts), 1),
            message=f"Sweep {court}",
        )
        run = start_source_run(
            session,
            job_type="DIARY_SWEEP",
            source="DJEN",
            court=court,
        )
        created = updated = rejected = 0
        try:
            criteria = DjenSearchCriteria(
                court=court,
                available_from=start,
                available_until=until,
                size=50,
            )
            page_result = client.search_all_pages(criteria, max_pages=5)
            items = page_result.get("items") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                out = ingest(
                    session,
                    source="DJEN",
                    discovery_channel="TRIBUNAL_SWEEP",
                    raw_payload=item,
                    settings=settings,
                    bootstrap_mode=bootstrap_mode,
                )
                if out.get("created"):
                    created += 1
                elif out.get("updated"):
                    updated += 1
                if out.get("rejected") or out.get("quarantined"):
                    rejected += 1
            finish_source_run(
                run,
                status="SUCCESS",
                items_received=len(items),
                items_created=created,
                items_updated=updated,
                items_rejected=rejected,
                cursor={
                    "pages_fetched": page_result.get("pages_fetched"),
                    "hit_max_pages": bool(page_result.get("hit_max_pages")),
                    "available_from": start.isoformat() if hasattr(start, "isoformat") else str(start),
                    "available_until": until.isoformat() if hasattr(until, "isoformat") else str(until),
                },
            )
            results.append(
                {
                    "court": court,
                    "status": "SUCCESS",
                    "received": len(items),
                    "created": created,
                    "updated": updated,
                    "rejected": rejected,
                }
            )
        except Exception as exc:  # noqa: BLE001
            finish_source_run(
                run,
                status="FAILED",
                items_created=created,
                items_updated=updated,
                items_rejected=rejected,
                error_code=getattr(exc, "code", type(exc).__name__),
                error_message=str(exc),
            )
            logger.warning(
                "diary_sweep_court_failed",
                extra={"extra": {"court": court, "error": str(exc)}},
            )
            results.append({"court": court, "status": "FAILED", "error": str(exc)})

    return {"courts": courts, "results": results}
