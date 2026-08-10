"""Descoberta nacional via DJEN (busca por critérios — sem tribunal prévio)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.canonical_oab import canonicalize_oab, OabCanonicalizeError
from monitor_jus.config import Settings, get_settings, load_fontes
from monitor_jus.db.models import Criterion, CriterionLink, SourceCheckpoint
from monitor_jus.exceptions import SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.ops_config import load_ops
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


def _djen_cfg(settings: Settings) -> dict[str, Any]:
    return load_fontes(settings).get("djen") or {}


def _ops_bundle(settings: Settings) -> dict[str, Any]:
    return load_ops(settings)


def _incremental_window(settings: Settings, session: Session) -> tuple[date, date]:
    """Janela curta do DJEN_POLL (overlap desde o último checkpoint)."""
    ops = _ops_bundle(settings)
    djen_cfg = _djen_cfg(settings)
    overlap_h = int(
        (ops.get("poll") or {}).get("overlap_hours")
        or djen_cfg.get("overlap_hours")
        or settings.djen_overlap_hours
        or 48
    )
    until = date.today()
    overlap_days = max(1, (overlap_h + 23) // 24)
    cp = session.scalar(
        select(SourceCheckpoint).where(
            SourceCheckpoint.source == "djen",
            SourceCheckpoint.checkpoint_key == "last_poll_success",
        )
    )
    if cp and isinstance(cp.cursor, dict) and cp.cursor.get("until"):
        try:
            last = date.fromisoformat(str(cp.cursor["until"])[:10])
            start = last - timedelta(days=overlap_days)
        except ValueError:
            start = until - timedelta(days=overlap_days)
    else:
        start = until - timedelta(days=overlap_days)
    return start, until


def _historical_window(
    settings: Settings,
    *,
    purpose: str = "discovery",
    lookback_days: int | None = None,
) -> tuple[date, date]:
    """Janela longa (BOOTSTRAP / HISTORICAL_DISCOVERY). Preferência: ops.yaml."""
    ops = _ops_bundle(settings)
    section = ops.get(purpose) if purpose in {"discovery", "bootstrap"} else ops.get("discovery")
    section = section if isinstance(section, dict) else {}
    djen_cfg = _djen_cfg(settings)
    days = int(
        lookback_days
        or section.get("lookback_days")
        or djen_cfg.get("historical_lookback_days")
        or settings.djen_historical_lookback_days
        or 1095
    )
    until = date.today()
    return until - timedelta(days=max(1, days)), until


def _resolve_window(
    settings: Settings,
    session: Session,
    *,
    mode: str,
    purpose: str = "discovery",
    lookback_days: int | None = None,
) -> tuple[date, date]:
    if mode == "historical":
        return _historical_window(
            settings, purpose=purpose, lookback_days=lookback_days
        )
    return _incremental_window(settings, session)


def _search_flags(settings: Settings, purpose: str) -> dict[str, bool]:
    ops = _ops_bundle(settings)
    section = ops.get("discovery") if isinstance(ops.get("discovery"), dict) else {}
    # Bootstrap herda os mesmos tipos de busca do discovery (config da UI)
    return {
        "OAB": bool(section.get("search_oabs", True)),
        "NOME": bool(section.get("search_names", True)),
        "PROCESSO": bool(section.get("search_processes", True)),
        "CNPJ": bool(section.get("search_companies", True)),
        "EMPRESA": bool(section.get("search_companies", True)),
    }


def _max_pages_for(settings: Settings, *, purpose: str, historical: bool) -> int:
    if not historical:
        return 10
    ops = _ops_bundle(settings)
    section = ops.get(purpose) if isinstance(ops.get(purpose), dict) else {}
    try:
        return max(5, min(200, int(section.get("max_pages") or 80)))
    except (TypeError, ValueError):
        return 80


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
    max_pages: int = 10,
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
            items = client.search_all_pages(criteria, max_pages=max_pages)
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
    max_pages: int = 10,
) -> dict[str, Any]:
    criteria = DjenSearchCriteria(
        lawyer_name=crit.value,
        available_from=available_from,
        available_until=available_until,
    )
    try:
        items = client.search_all_pages(criteria, max_pages=max_pages)
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
    max_pages: int = 5,
) -> dict[str, Any]:
    parts = normalize_cnj(crit.value) or normalize_cnj(crit.label or "")
    numero = parts.numero_formatado if parts else crit.value
    criteria = DjenSearchCriteria(
        process_number=numero,
        available_from=available_from,
        available_until=available_until,
    )
    try:
        items = client.search_all_pages(criteria, max_pages=max_pages)
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
    max_pages: int = 5,
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
            items = client.search_all_pages(criteria, max_pages=max_pages)
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
    mode: str = "incremental",
    purpose: str = "discovery",
    lookback_days: int | None = None,
) -> dict[str, Any]:
    """Poll DJEN.

    mode:
      - incremental: overlap curto desde checkpoint (DJEN_POLL horário/diário)
      - historical: lookback longo, ignora checkpoint (BOOTSTRAP / HISTORICAL_DISCOVERY)
    purpose: qual bloco do ops.yaml usar (discovery | bootstrap)
    """
    settings = settings or get_settings()
    fontes = load_fontes(settings)
    if (fontes.get("djen") or {}).get("enabled") is False or not settings.djen_enable:
        return {"status": "skipped", "reason": "djen_disabled"}

    client = DjenClient(settings)
    available_from, available_until = _resolve_window(
        settings,
        session,
        mode=mode,
        purpose=purpose,
        lookback_days=lookback_days,
    )
    historical = mode == "historical"
    max_pages = _max_pages_for(settings, purpose=purpose, historical=historical)
    flags = _search_flags(settings, purpose)
    criteria = list(session.scalars(select(Criterion).where(Criterion.active.is_(True))).all())
    criteria = [c for c in criteria if flags.get(c.criterion_type, True)]
    label = "HISTÓRICO" if historical else "POLL"
    report_progress(
        stage="djen_poll",
        done=0,
        total=max(len(criteria), 1),
        message=(
            f"DJEN {label} · {len(criteria)} critério(s) · "
            f"{available_from.isoformat()} → {available_until.isoformat()}"
        ),
        force=True,
    )

    summary: dict[str, Any] = {
        "mode": mode,
        "purpose": purpose,
        "window": {"from": available_from.isoformat(), "until": available_until.isoformat()},
        "search_flags": flags,
        "max_pages": max_pages,
        "oabs": [],
        "names": [],
        "processes": [],
        "companies": [],
        "errors": [],
        "skipped_criteria": 0,
        "total_active_criteria": len(criteria),
        "successful_criteria": 0,
        "checkpoint_advanced": False,
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
                        max_pages=max_pages,
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
                        max_pages=max_pages,
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
                        max_pages=max(5, max_pages // 4),
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
                        max_pages=max(5, max_pages // 4),
                    )
                )
            else:
                summary["skipped_criteria"] += 1
                continue
            summary["successful_criteria"] += 1
        except Exception as exc:  # noqa: BLE001
            # Falha de um critério não interrompe os demais
            logger.exception("djen_poll_criterion_failed")
            summary["errors"].append({"criterion": crit.value, "error": str(exc)})

    # Checkpoint só com sucesso total — falha parcial mantém cursor (overlap refaz janela)
    if not historical:
        total = int(summary["total_active_criteria"])
        ok = int(summary["successful_criteria"])
        if total == 0 or ok == total:
            _save_checkpoint(session, available_until)
            summary["checkpoint_advanced"] = True
        else:
            logger.warning(
                "djen_checkpoint_kept",
                extra={
                    "extra": {
                        "successful": ok,
                        "total": total,
                        "errors": len(summary["errors"]),
                    }
                },
            )
    report_progress(
        stage="djen_poll",
        done=len(criteria),
        total=max(len(criteria), 1),
        message=f"DJEN {label} concluído",
        force=True,
    )
    return summary


def run_discovery(
    session: Session,
    settings: Settings | None = None,
    *,
    bootstrap_mode: bool = False,
    mode: str = "historical",
    purpose: str = "discovery",
) -> dict[str, Any]:
    """Discovery nacional — por padrão histórico (bootstrap / HISTORICAL_DISCOVERY)."""
    return run_djen_poll(
        session,
        settings=settings,
        bootstrap_mode=bootstrap_mode,
        mode=mode,
        purpose=purpose,
    )


def backfill_oab_links_from_payloads(session: Session) -> int:
    """Religa processos às OABs monitoradas a partir do payload (DJEN estruturado + texto).

    Também varre comunicações do processo (`_extracted.oabs`) — cobre histórico
    descoberto só por nome em que a OAB veio nos destinatárioadvogados.
    """
    from monitor_jus.db.models import Communication, Process
    from monitor_jus.db.repository import Repository
    from monitor_jus.oab_match import (
        criterion_matches_oab,
        extract_oabs_from_payload,
        oab_identity,
        parse_oab_criterion_value,
    )

    repo = Repository(session)
    oab_criteria = [
        c
        for c in session.scalars(select(Criterion).where(Criterion.active.is_(True))).all()
        if c.criterion_type == "OAB"
    ]
    if not oab_criteria:
        return 0

    # OABs já vistas por comunicação (chave → identidades)
    comm_oabs: dict[str, set[tuple[str, str]]] = {}
    for comm in session.scalars(select(Communication)).all():
        cnj = (comm.numero_cnj or "").strip()
        if not cnj:
            continue
        ids = extract_oabs_from_payload(comm.payload)
        if ids:
            comm_oabs.setdefault(cnj, set()).update(ids)

    linked = 0
    for proc in session.scalars(select(Process)).all():
        identities = extract_oabs_from_payload(proc.payload)
        if proc.numero_cnj and proc.numero_cnj in comm_oabs:
            identities |= comm_oabs[proc.numero_cnj]
        if not identities:
            continue
        for crit in oab_criteria:
            parsed = parse_oab_criterion_value(crit.value)
            if not parsed:
                continue
            want = oab_identity(parsed[0], parsed[1])
            if want in identities or any(
                criterion_matches_oab(crit.value, ident) for ident in identities
            ):
                before = session.scalar(
                    select(CriterionLink).where(
                        CriterionLink.criterion_id == crit.id,
                        CriterionLink.process_id == proc.id,
                    )
                )
                repo.link_criterion_process(crit.id, proc.id)
                if before is None:
                    linked += 1
    return linked
