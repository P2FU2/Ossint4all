"""Descoberta nacional via DJEN (busca por critérios — sem tribunal prévio)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.canonical_oab import canonicalize_oab, OabCanonicalizeError
from monitor_jus.config import Settings, get_settings, load_fontes
from monitor_jus.db.models import Criterion, SourceCheckpoint
from monitor_jus.exceptions import SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.pipeline.communication_ingest import (
    finish_source_run,
    ingest,
    start_source_run,
)
from monitor_jus.progress import raise_if_cancelled, report as report_progress
from monitor_jus.sources.djen.client import DjenClient
from monitor_jus.sources.djen.criteria import DjenSearchCriteria
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)


def _overlap_window(settings: Settings, session: Session) -> tuple[date, date]:
    fontes = load_fontes(settings)
    djen_cfg = fontes.get("djen") or {}
    overlap_h = int(djen_cfg.get("overlap_hours") or settings.djen_overlap_hours or 48)
    until = date.today()
    # checkpoint de último sucesso
    cp = session.scalar(
        select(SourceCheckpoint).where(
            SourceCheckpoint.source == "djen",
            SourceCheckpoint.checkpoint_key == "last_poll_success",
        )
    )
    if cp and isinstance(cp.cursor, dict) and cp.cursor.get("until"):
        try:
            last = date.fromisoformat(str(cp.cursor["until"])[:10])
            start = last - timedelta(hours=overlap_h)  # type: ignore[arg-type]
            # timedelta hours on date: use days
            start = last - timedelta(days=max(1, overlap_h // 24))
        except ValueError:
            start = until - timedelta(days=max(1, overlap_h // 24))
    else:
        start = until - timedelta(days=max(1, overlap_h // 24))
    return start, until


def _save_checkpoint(session: Session, until: date) -> None:
    cp = session.scalar(
        select(SourceCheckpoint).where(
            SourceCheckpoint.source == "djen",
            SourceCheckpoint.checkpoint_key == "last_poll_success",
        )
    )
    cursor = {"until": until.isoformat(), "at": datetime.now(timezone.utc).isoformat()}
    if not cp:
        from uuid import uuid4

        session.add(
            SourceCheckpoint(
                id=str(uuid4()),
                source="djen",
                checkpoint_key="last_poll_success",
                cursor=cursor,
            )
        )
    else:
        cp.cursor = cursor
    session.flush()


def _ingest_items(
    session: Session,
    items: list[dict[str, Any]],
    *,
    channel: str,
    bootstrap_mode: bool,
    settings: Settings,
    job_type: str,
    criteria_id: str | None,
) -> dict[str, int]:
    run = start_source_run(
        session,
        job_type=job_type,
        source="DJEN",
        criteria_id=criteria_id,
    )
    created = updated = rejected = 0
    try:
        for item in items:
            if not isinstance(item, dict):
                continue
            out = ingest(
                session,
                source="DJEN",
                discovery_channel=channel,
                raw_payload=item,
                settings=settings,
                bootstrap_mode=bootstrap_mode,
                source_run_id=run.id,
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
        )
    except Exception as exc:  # noqa: BLE001
        finish_source_run(
            run,
            status="FAILED",
            items_received=len(items),
            items_created=created,
            items_updated=updated,
            items_rejected=rejected,
            error_code=getattr(exc, "code", "FAILED"),
            error_message=str(exc),
        )
        raise
    return {
        "received": len(items),
        "created": created,
        "updated": updated,
        "rejected": rejected,
    }


def search_oab_nationally(
    session: Session,
    client: DjenClient,
    crit: Criterion,
    *,
    available_from: date,
    available_until: date,
    bootstrap_mode: bool,
    settings: Settings,
) -> dict[str, Any]:
    try:
        oab = canonicalize_oab(crit.value)
    except OabCanonicalizeError as exc:
        return {"error": str(exc)}
    if not oab.state:
        return {"error": "OAB sem UF"}

    variants = [
        DjenSearchCriteria(
            oab_number=f"{oab.number}{oab.suffix or ''}",
            oab_state=oab.state,
            available_from=available_from,
            available_until=available_until,
        ),
        DjenSearchCriteria(
            oab_number=oab.number,
            oab_state=oab.state,
            available_from=available_from,
            available_until=available_until,
        ),
    ]
    # nome complementar (não confirma sozinho)
    if crit.label:
        variants.append(
            DjenSearchCriteria(
                lawyer_name=crit.label,
                available_from=available_from,
                available_until=available_until,
            )
        )

    totals = {"received": 0, "created": 0, "updated": 0, "rejected": 0}
    for criteria in variants:
        try:
            items = client.search_all_pages(criteria, max_pages=10)
        except SourceOutcomeError as exc:
            logger.warning(
                "djen_oab_search_failed",
                extra={"extra": {"criterion": crit.value, "code": exc.code, "msg": str(exc)}},
            )
            continue
        stats = _ingest_items(
            session,
            items,
            channel="OAB_SEARCH" if criteria.oab_number else "NAME_SEARCH",
            bootstrap_mode=bootstrap_mode,
            settings=settings,
            job_type="DJEN_POLL",
            criteria_id=crit.id,
        )
        for k in totals:
            totals[k] += stats[k]
    return totals


def search_name_nationally(
    session: Session,
    client: DjenClient,
    crit: Criterion,
    *,
    available_from: date,
    available_until: date,
    bootstrap_mode: bool,
    settings: Settings,
) -> dict[str, Any]:
    criteria = DjenSearchCriteria(
        lawyer_name=crit.value,
        available_from=available_from,
        available_until=available_until,
    )
    try:
        items = client.search_all_pages(criteria, max_pages=10)
    except SourceOutcomeError as exc:
        logger.warning("djen_name_search_failed", extra={"extra": {"msg": str(exc)}})
        return {"error": str(exc)}
    return _ingest_items(
        session,
        items,
        channel="NAME_SEARCH",
        bootstrap_mode=bootstrap_mode,
        settings=settings,
        job_type="DJEN_POLL",
        criteria_id=crit.id,
    )


def search_process_nationally(
    session: Session,
    client: DjenClient,
    crit: Criterion,
    *,
    available_from: date,
    available_until: date,
    bootstrap_mode: bool,
    settings: Settings,
) -> dict[str, Any]:
    parts = normalize_cnj(crit.value) or normalize_cnj(crit.label or "")
    numero = parts.numero_formatado if parts else crit.value
    criteria = DjenSearchCriteria(
        process_number=numero,
        available_from=available_from,
        available_until=available_until,
    )
    try:
        items = client.search_all_pages(criteria, max_pages=5)
    except SourceOutcomeError as exc:
        return {"error": str(exc)}
    return _ingest_items(
        session,
        items,
        channel="PROCESS_SEARCH",
        bootstrap_mode=bootstrap_mode,
        settings=settings,
        job_type="DJEN_POLL",
        criteria_id=crit.id,
    )


def search_company_nationally(
    session: Session,
    client: DjenClient,
    crit: Criterion,
    *,
    available_from: date,
    available_until: date,
    bootstrap_mode: bool,
    settings: Settings,
) -> dict[str, Any]:
    name = (crit.label or crit.meta or {}).get("nome") if isinstance(crit.meta, dict) else None
    name = name or crit.label or crit.value
    aliases = []
    if isinstance(crit.meta, dict):
        aliases = list(crit.meta.get("aliases") or [])
    totals = {"received": 0, "created": 0, "updated": 0, "rejected": 0}
    for term in [name, *aliases]:
        if not term:
            continue
        criteria = DjenSearchCriteria(
            text=str(term),
            available_from=available_from,
            available_until=available_until,
        )
        try:
            items = client.search_all_pages(criteria, max_pages=5)
        except SourceOutcomeError:
            continue
        stats = _ingest_items(
            session,
            items,
            channel="COMPANY_SEARCH",
            bootstrap_mode=bootstrap_mode,
            settings=settings,
            job_type="DJEN_POLL",
            criteria_id=crit.id,
        )
        for k in totals:
            totals[k] += stats[k]
    return totals


def run_djen_poll(
    session: Session,
    settings: Settings | None = None,
    *,
    bootstrap_mode: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    fontes = load_fontes(settings)
    if (fontes.get("djen") or {}).get("enabled") is False or not settings.djen_enable:
        return {"status": "skipped", "reason": "djen_disabled"}

    client = DjenClient(settings)
    available_from, available_until = _overlap_window(settings, session)
    criteria = list(session.scalars(select(Criterion).where(Criterion.active.is_(True))).all())
    report_progress(
        stage="djen_poll",
        done=0,
        total=max(len(criteria), 1),
        message=f"DJEN_POLL · {len(criteria)} critério(s)",
        force=True,
    )

    summary: dict[str, Any] = {
        "window": {"from": available_from.isoformat(), "until": available_until.isoformat()},
        "oabs": [],
        "names": [],
        "processes": [],
        "companies": [],
        "errors": [],
    }

    for idx, crit in enumerate(criteria):
        raise_if_cancelled()
        report_progress(
            stage="djen_poll",
            done=idx,
            total=max(len(criteria), 1),
            message=f"Buscando {crit.criterion_type}:{crit.value}",
        )
        try:
            if crit.criterion_type == "OAB":
                summary["oabs"].append(
                    search_oab_nationally(
                        session,
                        client,
                        crit,
                        available_from=available_from,
                        available_until=available_until,
                        bootstrap_mode=bootstrap_mode,
                        settings=settings,
                    )
                )
            elif crit.criterion_type == "NOME":
                summary["names"].append(
                    search_name_nationally(
                        session,
                        client,
                        crit,
                        available_from=available_from,
                        available_until=available_until,
                        bootstrap_mode=bootstrap_mode,
                        settings=settings,
                    )
                )
            elif crit.criterion_type == "PROCESSO":
                summary["processes"].append(
                    search_process_nationally(
                        session,
                        client,
                        crit,
                        available_from=available_from,
                        available_until=available_until,
                        bootstrap_mode=bootstrap_mode,
                        settings=settings,
                    )
                )
            elif crit.criterion_type in {"CNPJ", "EMPRESA"}:
                summary["companies"].append(
                    search_company_nationally(
                        session,
                        client,
                        crit,
                        available_from=available_from,
                        available_until=available_until,
                        bootstrap_mode=bootstrap_mode,
                        settings=settings,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            # Falha de um critério não interrompe os demais
            logger.exception("djen_poll_criterion_failed")
            summary["errors"].append({"criterion": crit.value, "error": str(exc)})

    _save_checkpoint(session, available_until)
    report_progress(
        stage="djen_poll",
        done=len(criteria),
        total=max(len(criteria), 1),
        message="DJEN_POLL concluído",
        force=True,
    )
    return summary


def run_discovery(
    session: Session,
    settings: Settings | None = None,
    *,
    bootstrap_mode: bool = False,
) -> dict[str, Any]:
    """Compat: discovery = DJEN_POLL nacional."""
    return run_djen_poll(session, settings=settings, bootstrap_mode=bootstrap_mode)


def backfill_oab_links_from_payloads(session: Session) -> int:
    """Religa processos às OABs monitoradas com base no payload (match tipado)."""
    from monitor_jus.db.models import Process
    from monitor_jus.db.repository import Repository
    from monitor_jus.matching import extract_oabs_from_text
    from monitor_jus.canonical_oab import canonicalize_oab

    repo = Repository(session)
    oab_criteria = [
        c
        for c in session.scalars(select(Criterion).where(Criterion.active.is_(True))).all()
        if c.criterion_type == "OAB"
    ]
    linked = 0
    for proc in session.scalars(select(Process)).all():
        blob = ""
        if isinstance(proc.payload, dict):
            import json

            blob = json.dumps(proc.payload, ensure_ascii=False)
        oabs = extract_oabs_from_text(blob)
        for crit in oab_criteria:
            try:
                crit_oab = canonicalize_oab(crit.value)
            except OabCanonicalizeError:
                continue
            for hit in oabs:
                if hit.matches_criterion(crit_oab):
                    repo.link_criterion_process(crit.id, proc.id)
                    linked += 1
                    break
    return linked
