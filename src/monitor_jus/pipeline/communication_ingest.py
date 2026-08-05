"""Ingestão única de comunicações (DJEN_POLL e DIARY_SWEEP)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import Communication, Criterion, Event, Process, SourceRun
from monitor_jus.db.repository import Repository
from monitor_jus.logging_setup import get_logger
from monitor_jus.matching import MatchStatus, MonitoredCriterion, classify_match
from monitor_jus.models import EventType, NotifyStatus
from monitor_jus.official_portal import resolve_official_link_result
from monitor_jus.pipeline.identity import sha256_hex
from monitor_jus.pipeline.relations import maybe_extract_relations
from monitor_jus.sources.djen.extract import extract_communication
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)


def _normalized_text_hash(text: str) -> str:
    norm = " ".join((text or "").lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def build_communication_key(
    *,
    source: str,
    external_id: str | None,
    process_number: str | None,
    availability_date: str | None,
    raw_text: str,
) -> str:
    if external_id:
        return f"{source}:{external_id}"
    digest = hashlib.sha256(
        "|".join(
            [
                source,
                external_id or "",
                process_number or "",
                availability_date or "",
                _normalized_text_hash(raw_text),
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"{source}:h:{digest[:40]}"


def _load_criteria(session: Session) -> list[MonitoredCriterion]:
    rows = list(session.scalars(select(Criterion).where(Criterion.active.is_(True))).all())
    out: list[MonitoredCriterion] = []
    for r in rows:
        meta = r.meta or {}
        out.append(
            MonitoredCriterion(
                criterion_type=r.criterion_type,
                value=r.value,
                label=r.label,
                meta=meta,
                requires_secondary_evidence=bool(meta.get("requires_secondary_evidence")),
            )
        )
    return out


def ingest(
    session: Session,
    *,
    source: str,
    discovery_channel: str,
    raw_payload: dict[str, Any],
    settings: Settings | None = None,
    bootstrap_mode: bool = False,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    extracted = extract_communication(raw_payload)
    criteria = _load_criteria(session)

    evidence = classify_match(
        process_number=extracted.get("process_number"),
        court=extracted.get("court"),
        text=extracted.get("raw_text") or "",
        lawyer_names=extracted.get("lawyer_names") or [],
        oabs=extracted.get("oabs") or [],
        criteria=criteria,
    )

    key = build_communication_key(
        source=source,
        external_id=extracted.get("external_id"),
        process_number=extracted.get("process_number"),
        availability_date=extracted.get("availability_date"),
        raw_text=extracted.get("raw_text") or "",
    )

    result = {
        "communication_key": key,
        "match_status": evidence.status.value,
        "created": False,
        "updated": False,
        "rejected": evidence.status == MatchStatus.REJECTED,
        "quarantined": evidence.status == MatchStatus.AMBIGUOUS,
        "process_id": None,
        "event_id": None,
    }

    if evidence.status == MatchStatus.REJECTED:
        return result

    existing = session.scalar(
        select(Communication).where(Communication.communication_key == key)
    )
    now = datetime.now(timezone.utc)
    channels = [discovery_channel]
    payload_extra = {
        **(raw_payload if isinstance(raw_payload, dict) else {"raw": raw_payload}),
        "_match": {
            "status": evidence.status.value,
            "reasons": evidence.reasons,
            "matched_criteria": evidence.matched_criteria,
        },
        "_discovery_channels": channels,
        "_extracted": {
            "process_number": extracted.get("process_number"),
            "court": extracted.get("court"),
            "lawyer_names": extracted.get("lawyer_names"),
            "oabs": [o.canonical or o.original for o in (extracted.get("oabs") or [])],
        },
    }

    if existing:
        prev_channels = []
        if isinstance(existing.payload, dict):
            prev_channels = list(existing.payload.get("_discovery_channels") or [])
        merged_channels = list(dict.fromkeys([*prev_channels, discovery_channel]))
        payload_extra["_discovery_channels"] = merged_channels
        existing.last_seen_at = now
        existing.payload = payload_extra
        existing.match_status = evidence.status.value
        existing.match_evidence_json = {
            "reasons": evidence.reasons,
            "matched_criteria": evidence.matched_criteria,
        }
        existing.discovery_channels_json = merged_channels
        # Releitura: religa critérios (ex.: OAB que faltava no 1º match por nome)
        cnj_existing = normalize_cnj(extracted.get("process_number") or existing.numero_cnj or "")
        if cnj_existing and evidence.matched_criteria:
            proc_existing = session.scalar(
                select(Process).where(Process.numero_cnj == cnj_existing.numero_formatado)
            )
            if proc_existing:
                for crit_value in evidence.matched_criteria:
                    crit = session.scalar(
                        select(Criterion).where(
                            Criterion.active.is_(True),
                            Criterion.value == crit_value,
                        )
                    )
                    if crit:
                        repo.link_criterion_process(crit.id, proc_existing.id)
                result["process_id"] = proc_existing.id
        result["updated"] = True
        session.flush()
        return result

    if evidence.status == MatchStatus.AMBIGUOUS:
        from monitor_jus.db.models import EventQuarantine

        session.add(
            EventQuarantine(
                id=str(uuid4()),
                reason="AMBIGUOUS_IDENTITY",
                payload=payload_extra,
                details="; ".join(evidence.reasons),
            )
        )
        result["quarantined"] = True
        session.flush()
        return result

    # CONFIRMED / PROBABLE / PENDING_CNA → persist communication
    body = extracted.get("raw_text") or ""
    payload_hash = hashlib.sha256(
        json.dumps(payload_extra, sort_keys=True, default=str).encode()
    ).hexdigest()[:64]

    comm = Communication(
        id=str(uuid4()),
        communication_key=key,
        communication_type=extracted.get("communication_type") or "COMUNICACAO",
        numero_cnj=extracted.get("process_number"),
        source_name=source,
        source_event_id=extracted.get("external_id"),
        title=f"{extracted.get('court') or 'DJEN'} · {extracted.get('communication_type')}",
        body=body[:8000] if body else None,
        published_at=None,
        payload_hash=payload_hash,
        payload=payload_extra,
        match_status=evidence.status.value,
        match_evidence_json={
            "reasons": evidence.reasons,
            "matched_criteria": evidence.matched_criteria,
        },
        discovery_channels_json=channels,
        notification_status=(
            NotifyStatus.IGNORED.value
            if bootstrap_mode
            else NotifyStatus.PENDING_NOTIFY.value
        ),
    )
    session.add(comm)
    result["created"] = True

    process_id = None
    cnj = normalize_cnj(extracted.get("process_number") or "")
    if cnj and evidence.status in {
        MatchStatus.CONFIRMED_OAB,
        MatchStatus.CONFIRMED_PROCESS,
        MatchStatus.PROBABLE_NAME,
    }:
        link = resolve_official_link_result(
            cnj.numero_formatado,
            tribunal=extracted.get("court"),
            payload=raw_payload,
            classe=extracted.get("nome_classe"),
        )
        proc = repo.upsert_process(
            cnj.numero_formatado,
            cnj.numero_digits,
            tribunal=extracted.get("court"),
            classe=extracted.get("nome_classe"),
            orgao_julgador=extracted.get("nome_orgao"),
            payload={
                "source": source,
                "djen": raw_payload,
                "official_link": link.url,
                "official_link_type": link.link_type,
            },
        )
        if hasattr(proc, "official_link"):
            proc.official_link = link.url or None
            proc.official_link_type = link.link_type
        if extracted.get("nome_classe"):
            proc.classe = proc.classe or extracted.get("nome_classe")
        if extracted.get("nome_orgao"):
            proc.orgao_julgador = proc.orgao_julgador or extracted.get("nome_orgao")
        process_id = proc.id
        result["process_id"] = process_id

        # Link critérios
        for crit_value in evidence.matched_criteria:
            crit = session.scalar(
                select(Criterion).where(
                    Criterion.active.is_(True),
                    Criterion.value == crit_value,
                )
            )
            if crit:
                repo.link_criterion_process(crit.id, proc.id)

        maybe_extract_relations(session, proc, body, source=source)

    # Evento notificável
    if evidence.status in {
        MatchStatus.CONFIRMED_OAB,
        MatchStatus.CONFIRMED_PROCESS,
    } or (
        evidence.status == MatchStatus.PROBABLE_NAME
    ):
        evt_identity = sha256_hex(
            EventType.PUBLICACAO_DJEN.value,
            source,
            extracted.get("external_id") or key,
            extracted.get("process_number") or "",
        )
        notify = (
            NotifyStatus.IGNORED.value
            if bootstrap_mode
            else (
                NotifyStatus.PENDING_NOTIFY.value
                if evidence.status != MatchStatus.PROBABLE_NAME
                else NotifyStatus.PENDING_NOTIFY.value
            )
        )
        link = resolve_official_link_result(
            extracted.get("process_number"),
            tribunal=extracted.get("court"),
            payload=raw_payload,
        )
        event = Event(
            id=str(uuid4()),
            event_type=EventType.PUBLICACAO_DJEN.value,
            event_identity_key=evt_identity,
            notify_status=notify,
            source_name=source,
            source_event_id=extracted.get("external_id"),
            numero_cnj=extracted.get("process_number"),
            tribunal=extracted.get("court"),
            title=comm.title,
            description=(body or "")[:2000],
            priority="media",
            official_link=link.url or None,
            criterion_refs=evidence.matched_criteria,
            payload_hash=payload_hash,
            requires_name_validation=evidence.status == MatchStatus.PROBABLE_NAME,
        )
        session.add(event)
        result["event_id"] = event.id
        if evidence.status == MatchStatus.PROBABLE_NAME:
            event.requires_name_validation = True

    session.flush()
    logger.info(
        "communication_ingested",
        extra={
            "extra": {
                "key": key,
                "channel": discovery_channel,
                "match": evidence.status.value,
                "created": result["created"],
            }
        },
    )
    return result


def start_source_run(
    session: Session,
    *,
    job_type: str,
    source: str,
    court: str | None = None,
    criteria_id: str | None = None,
) -> SourceRun:
    run = SourceRun(
        id=str(uuid4()),
        job_type=job_type,
        source=source,
        court=court,
        criteria_id=criteria_id,
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
    )
    session.add(run)
    session.flush()
    return run


def finish_source_run(
    run: SourceRun,
    *,
    status: str,
    items_received: int = 0,
    items_created: int = 0,
    items_updated: int = 0,
    items_rejected: int = 0,
    http_status: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    cursor: dict[str, Any] | None = None,
) -> None:
    run.finished_at = datetime.now(timezone.utc)
    run.status = status
    run.items_received = items_received
    run.items_created = items_created
    run.items_updated = items_updated
    run.items_rejected = items_rejected
    run.http_status = http_status
    run.error_code = error_code
    run.error_message = error_message
    run.cursor_json = cursor
