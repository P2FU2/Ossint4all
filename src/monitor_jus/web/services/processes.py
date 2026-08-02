"""Acervo e detalhe de processos."""

from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.db.models import (
    Communication,
    Criterion,
    CriterionLink,
    Event,
    Process,
    ProcessMovement,
)
from monitor_jus.official_portal import resolve_official_link
from monitor_jus.pipeline.portfolio import build_portfolio, classify_outcome
from monitor_jus.security import redact_text


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


def list_processes(
    session: Session,
    *,
    q: str = "",
    tribunal: str = "",
    oab: str = "",
    outcome: str = "",
    pending_only: bool = False,
) -> dict[str, Any]:
    portfolio = build_portfolio(session)
    rows = portfolio["processes"]

    pending_cnjs: set[str] = set()
    if pending_only:
        pending_cnjs = {
            e.numero_cnj
            for e in session.scalars(
                select(Event).where(Event.notify_status == "PENDING_NOTIFY", Event.numero_cnj.is_not(None))
            ).all()
            if e.numero_cnj
        }

    q_norm = (q or "").strip().lower()
    tribunal_norm = (tribunal or "").strip().lower()
    oab_norm = (oab or "").strip().lower()
    outcome_norm = (outcome or "").strip().lower()

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if q_norm and q_norm not in row["numero_cnj"].lower() and q_norm not in (row.get("classe") or "").lower():
            if q_norm not in (row.get("assunto") or "").lower():
                continue
        if tribunal_norm and tribunal_norm not in (row.get("tribunal") or "").lower():
            continue
        if oab_norm and oab_norm not in (row.get("criteria") or "").lower():
            continue
        if outcome_norm and row.get("outcome") != outcome_norm:
            continue
        if pending_only and row["numero_cnj"] not in pending_cnjs:
            continue
        filtered.append(row)

    tribunals = sorted({r["tribunal"] for r in rows if r.get("tribunal")})
    return {
        "processes": filtered,
        "total": len(filtered),
        "total_all": len(rows),
        "tribunals": tribunals,
        "filters": {
            "q": q,
            "tribunal": tribunal,
            "oab": oab,
            "outcome": outcome,
            "pending_only": pending_only,
        },
        "by_outcome": portfolio.get("by_outcome") or {},
    }


def processes_csv(session: Session, **filters: Any) -> str:
    data = list_processes(session, **filters)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "numero_cnj",
            "tribunal",
            "classe",
            "assunto",
            "situacao",
            "outcome",
            "grau",
            "criteria",
            "last_movement_at",
            "official_link",
            "baseline",
        ]
    )
    for r in data["processes"]:
        writer.writerow(
            [
                r["numero_cnj"],
                r["tribunal"],
                r["classe"],
                r["assunto"],
                r["situacao"],
                r["outcome"],
                r["grau"],
                r["criteria"],
                r["last_movement_at"],
                r.get("official_link") or "",
                r.get("baseline"),
            ]
        )
    return buf.getvalue()


def get_process_detail(session: Session, process_id: str) -> dict[str, Any] | None:
    proc = session.get(Process, process_id)
    if not proc:
        return None

    payload = proc.payload if isinstance(proc.payload, dict) else {}
    last_step = None
    if isinstance(payload.get("last_step"), dict):
        last_step = str(payload["last_step"].get("content") or payload["last_step"].get("nome") or "")
    outcome = classify_outcome(proc.situacao, last_step=last_step)

    links = list(
        session.scalars(select(CriterionLink).where(CriterionLink.process_id == proc.id)).all()
    )
    criteria_rows = []
    for link in links:
        crit = session.get(Criterion, link.criterion_id)
        if crit:
            criteria_rows.append(
                {
                    "type": crit.criterion_type,
                    "value": crit.value,
                    "label": crit.label or crit.value,
                }
            )

    movements = list(
        session.scalars(
            select(ProcessMovement)
            .where(ProcessMovement.process_id == proc.id)
            .order_by(
                ProcessMovement.data_hora.desc().nulls_last(),
                ProcessMovement.first_seen_at.desc(),
            )
            .limit(80)
        ).all()
    )
    communications = list(
        session.scalars(
            select(Communication)
            .where(Communication.numero_cnj == proc.numero_cnj)
            .order_by(Communication.published_at.desc().nulls_last())
            .limit(40)
        ).all()
    )
    events = list(
        session.scalars(
            select(Event)
            .where(Event.numero_cnj == proc.numero_cnj)
            .order_by(Event.created_at.desc())
            .limit(60)
        ).all()
    )

    timeline: list[dict[str, Any]] = []
    for m in movements:
        timeline.append(
            {
                "kind": "movimentacao",
                "when": m.data_hora or m.first_seen_at,
                "when_fmt": _fmt(m.data_hora or m.first_seen_at),
                "title": m.nome or "Movimentação",
                "body": redact_text(m.complemento or ""),
                "source": m.source_name,
            }
        )
    for c in communications:
        timeline.append(
            {
                "kind": "comunicacao",
                "when": c.published_at or c.first_seen_at,
                "when_fmt": _fmt(c.published_at or c.first_seen_at),
                "title": c.title or c.communication_type,
                "body": redact_text((c.body or "")[:500]),
                "source": c.source_name,
            }
        )
    for e in events:
        timeline.append(
            {
                "kind": "evento",
                "when": e.created_at,
                "when_fmt": _fmt(e.created_at),
                "title": e.title or e.event_type,
                "body": redact_text(e.summary or e.description or ""),
                "source": e.source_name,
                "priority": e.priority,
                "notify_status": e.notify_status,
                "event_id": e.id,
            }
        )
    timeline.sort(key=lambda x: x["when"] or utc_min(), reverse=True)

    return {
        "id": proc.id,
        "numero_cnj": proc.numero_cnj,
        "tribunal": proc.tribunal or "—",
        "classe": proc.classe or "—",
        "assunto": proc.assunto or "—",
        "situacao": proc.situacao or "—",
        "grau": proc.grau or "—",
        "orgao_julgador": proc.orgao_julgador or "—",
        "outcome": outcome,
        "baseline": proc.baseline,
        "data_distribuicao": _fmt(proc.data_distribuicao),
        "last_checked_at": _fmt(proc.last_checked_at),
        "last_movement_at": _fmt(proc.last_movement_at),
        "official_link": resolve_official_link(
            proc.numero_cnj, tribunal=proc.tribunal, payload=payload
        ),
        "criteria": criteria_rows,
        "timeline": timeline[:120],
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "title": e.title,
                "summary": redact_text(e.summary or ""),
                "priority": e.priority,
                "notify_status": e.notify_status,
                "created_at": _fmt(e.created_at),
                "official_link": e.official_link,
            }
            for e in events
        ],
        "payload_preview": redact_text(str(payload)[:2000]) if payload else "",
    }


def utc_min() -> Any:
    from datetime import datetime, timezone

    return datetime.min.replace(tzinfo=timezone.utc)
