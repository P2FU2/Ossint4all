"""Snapshot de portfólio: processos ativos, status e estatísticas."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.db.models import Criterion, CriterionLink, Process
from monitor_jus.official_portal import resolve_official_link


def classify_outcome(situacao: str | None, *, last_step: str | None = None) -> str:
    """Classifica resultado estimado a partir do status textual.

    Retornos: ativo | exito | derrota | encerrado | indefinido
    """
    blob = f"{situacao or ''} {last_step or ''}".lower()
    if not blob.strip():
        return "indefinido"
    if any(
        k in blob
        for k in (
            "improcedente",
            "denegad",
            "desfavor",
            "rejeitad",
            "negado provimento",
        )
    ):
        return "derrota"
    if any(
        k in blob
        for k in (
            "procedente",
            "parcialmente procedente",
            "acordo",
            "homolog",
            "favoráv",
            "transação",
            "transacao",
            "dado provimento",
        )
    ):
        return "exito"
    if any(
        k in blob
        for k in (
            "arquiv",
            "baix",
            "extin",
            "transitad",
            "finalizad",
            "encerrad",
        )
    ):
        return "encerrado"
    if any(k in blob for k in ("andamento", "ativo", "curso", "tramit", "pendente")):
        return "ativo"
    return "indefinido"


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    try:
        return value.astimezone().strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return value.strftime("%d/%m/%Y")


def build_portfolio(session: Session) -> dict[str, Any]:
    processes = list(session.scalars(select(Process).order_by(Process.numero_cnj.asc())).all())
    criteria = {
        c.id: c
        for c in session.scalars(select(Criterion).where(Criterion.active.is_(True))).all()
    }
    links = list(session.scalars(select(CriterionLink)).all())

    process_criteria: dict[str, list[str]] = defaultdict(list)
    for link in links:
        if not link.process_id:
            continue
        crit = criteria.get(link.criterion_id)
        if not crit:
            continue
        label = crit.label or f"{crit.criterion_type}:{crit.value}"
        if crit.criterion_type == "OAB":
            # value = UF:numero
            parts = crit.value.split(":", 1)
            if len(parts) == 2:
                label = f"OAB {parts[1]}/{parts[0]}"
            else:
                label = f"OAB {crit.value}"
        process_criteria[link.process_id].append(label)

    by_oab: Counter[str] = Counter()
    by_tribunal: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []

    for proc in processes:
        payload = proc.payload if isinstance(proc.payload, dict) else {}
        last_step = None
        if isinstance(payload.get("last_step"), dict):
            last_step = str(payload["last_step"].get("content") or payload["last_step"].get("nome") or "")
        elif payload.get("last_step_content"):
            last_step = str(payload.get("last_step_content"))

        outcome = classify_outcome(proc.situacao, last_step=last_step)
        by_outcome[outcome] += 1
        tribunal = proc.tribunal or "N/D"
        by_tribunal[tribunal] += 1

        crits = process_criteria.get(proc.id) or ["—"]
        for c in crits:
            if c.startswith("OAB "):
                by_oab[c] += 1

        rows.append(
            {
                "id": proc.id,
                "numero_cnj": proc.numero_cnj,
                "tribunal": tribunal,
                "classe": proc.classe or "—",
                "assunto": proc.assunto or "—",
                "situacao": proc.situacao or "—",
                "outcome": outcome,
                "grau": proc.grau or "—",
                "orgao_julgador": proc.orgao_julgador or "—",
                "data_distribuicao": _fmt_dt(proc.data_distribuicao),
                "last_checked_at": _fmt_dt(proc.last_checked_at),
                "last_movement_at": _fmt_dt(proc.last_movement_at),
                "criteria": ", ".join(crits),
                "baseline": proc.baseline,
                "official_link": resolve_official_link(
                    proc.numero_cnj,
                    tribunal=tribunal,
                    payload=payload if isinstance(payload, dict) else None,
                ),
            }
        )

    total = len(processes)
    decided = by_outcome.get("exito", 0) + by_outcome.get("derrota", 0)
    win_rate = (by_outcome.get("exito", 0) / decided * 100.0) if decided else None
    active_count = by_outcome.get("ativo", 0) + by_outcome.get("indefinido", 0)

    return {
        "total_processes": total,
        "active_count": active_count,
        "closed_count": by_outcome.get("encerrado", 0),
        "win_count": by_outcome.get("exito", 0),
        "loss_count": by_outcome.get("derrota", 0),
        "decided_count": decided,
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "by_oab": dict(sorted(by_oab.items(), key=lambda x: (-x[1], x[0]))),
        "by_tribunal": dict(sorted(by_tribunal.items(), key=lambda x: (-x[1], x[0]))),
        "by_outcome": dict(by_outcome),
        "processes": rows,
        "oab_criteria_count": sum(1 for c in criteria.values() if c.criterion_type == "OAB"),
    }
