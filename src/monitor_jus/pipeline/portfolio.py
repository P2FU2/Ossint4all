"""Snapshot de portfólio: processos ativos, status e estatísticas."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from monitor_jus.db.models import Criterion, CriterionLink, Process
from monitor_jus.official_portal import resolve_official_link
from monitor_jus.pipeline.status_oficial import (
    is_placeholder_status,
    resolve_situacao_oficial,
)

_PLACEHOLDERS = {
    "",
    "-",
    "---",
    "—",
    "n/d",
    "nd",
    "n.d.",
    "null",
    "none",
    "inconsistente",
    "desconhecido",
    "sem informação",
    "sem informacao",
}

_DERROTA = (
    "improcedente",
    "denegad",
    "desfavor",
    "rejeitad",
    "negado provimento",
    "não provido",
    "nao provido",
    "recurso não conhecido",
    "recurso nao conhecido",
    "extinto sem resolução do mérito",
    "extinto sem resolucao do merito",
)

_EXITO = (
    "parcialmente procedente",
    "procedente",
    "acordo",
    "homolog",
    "favoráv",
    "favorav",
    "transação",
    "transacao",
    "dado provimento",
    "provido",
    "concedida a segurança",
    "concedida a seguranca",
    "julgado procedente",
)

_ENCERRADO = (
    "arquivado definitivamente",
    "arquivamento definitivo",
    "arquiv",
    "baixado",
    "baixa definitiva",
    "extin",
    "extinto",
    "transitad",
    "finalizad",
    "encerrad",
    "baix",
    "sobrestado definitivamente",
)

_TRAMITACAO = (
    "andamento",
    "ativo",
    "em curso",
    "tramit",
    "pendente",
    "conclus",
    "juntada",
    "redistribu",
    "intima",
    "despacho",
    "remessa",
    "remetid",
    "vista",
    "publica",
    "ato ordinat",
    "aguardando",
    "cumprimento",
    "execução",
    "execucao",
    "expedi",
    "certific",
    "citação",
    "citacao",
    "audiência",
    "audiencia",
    "sentença",
    "sentenca",
    "prazo",
    "manifest",
    "petição",
    "peticao",
    "distribui",
    "recebiment",
    "processamento",
    "apens",
    "suspens",
    "sobrestad",
    "grau de recurso",
)


def classify_outcome(situacao: str | None, *, last_step: str | None = None) -> str:
    """Classifica resultado estimado a partir do status textual.

    Retornos: ativo | exito | derrota | encerrado | indefinido
    """
    situacao_raw = (situacao or "").strip()
    last_raw = (last_step or "").strip()
    blob = f"{situacao_raw} {last_raw}".lower().strip()
    situacao_l = situacao_raw.lower()

    if situacao_l in _PLACEHOLDERS and (not last_raw or last_raw.lower() in _PLACEHOLDERS):
        return "indefinido"
    if not blob or blob in _PLACEHOLDERS:
        return "indefinido"

    if any(k in blob for k in _DERROTA):
        return "derrota"
    if any(k in blob for k in _EXITO):
        return "exito"
    if any(k in blob for k in _ENCERRADO):
        return "encerrado"
    if any(k in blob for k in _TRAMITACAO):
        return "ativo"
    if len(blob) >= 4 and situacao_l not in _PLACEHOLDERS:
        return "ativo"
    return "indefinido"


def criterion_display_label(crit: Criterion) -> str:
    """Rótulo amigável do critério (prioriza OAB formatada)."""
    if crit.criterion_type == "OAB":
        parts = crit.value.split(":", 1)
        if len(parts) == 2:
            return f"OAB {parts[1]}/{parts[0]}"
        return f"OAB {crit.value}"
    if crit.criterion_type == "NOME":
        return f"Nome · {crit.label or crit.value}"
    if crit.criterion_type == "CPF":
        return f"CPF · {crit.label or crit.value}"
    if crit.criterion_type == "CNPJ":
        return f"CNPJ · {crit.label or crit.value}"
    return crit.label or f"{crit.criterion_type}:{crit.value}"


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    try:
        return value.astimezone().strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return value.strftime("%d/%m/%Y")


def _truncate(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def load_process_criteria(session: Session) -> tuple[dict[str, Criterion], dict[str, list[str]]]:
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
        process_criteria[link.process_id].append(criterion_display_label(crit))
    return criteria, process_criteria


def _include_all_oab_criteria(criteria: dict[str, Criterion], by_oab: Counter[str]) -> None:
    """Garante que toda OAB ativa apareça no painel, mesmo com 0 processos vinculados."""
    for crit in criteria.values():
        if crit.criterion_type != "OAB":
            continue
        label = criterion_display_label(crit)
        if label not in by_oab:
            by_oab[label] = 0


def _stats_from_counters(
    *,
    total: int,
    by_outcome: Counter[str],
    by_oab: Counter[str],
    by_tribunal: Counter[str],
    oab_criteria_count: int,
    processes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "total_processes": total,
        "active_count": by_outcome.get("ativo", 0),
        "undefined_count": by_outcome.get("indefinido", 0),
        "closed_count": by_outcome.get("encerrado", 0),
        "by_oab": dict(sorted(by_oab.items(), key=lambda x: (-x[1], x[0]))),
        "by_tribunal": dict(sorted(by_tribunal.items(), key=lambda x: (-x[1], x[0]))),
        "by_outcome": dict(by_outcome),
        "processes": processes or [],
        "oab_criteria_count": oab_criteria_count,
    }


def build_portfolio_stats(session: Session) -> dict[str, Any]:
    """Agregados leves para o dashboard — sem payload JSON nem lista completa."""
    processes = list(
        session.scalars(
            select(Process).options(
                load_only(
                    Process.id,
                    Process.situacao,
                    Process.tribunal,
                )
            )
        ).all()
    )
    criteria, process_criteria = load_process_criteria(session)

    by_oab: Counter[str] = Counter()
    by_tribunal: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()

    for proc in processes:
        outcome = classify_outcome(proc.situacao)
        by_outcome[outcome] += 1
        tribunal = proc.tribunal or "N/D"
        by_tribunal[tribunal] += 1
        for c in process_criteria.get(proc.id) or []:
            if c.startswith("OAB "):
                by_oab[c] += 1

    _include_all_oab_criteria(criteria, by_oab)

    return _stats_from_counters(
        total=len(processes),
        by_outcome=by_outcome,
        by_oab=by_oab,
        by_tribunal=by_tribunal,
        oab_criteria_count=sum(1 for c in criteria.values() if c.criterion_type == "OAB"),
    )


def serialize_process_row(
    proc: Process,
    *,
    criteria_labels: list[str] | None = None,
    include_payload: bool = False,
    payload: dict[str, Any] | None = None,
    last_movement: str | None = None,
) -> dict[str, Any]:
    """Serializa um processo para UI/CSV (payload opcional)."""
    if payload is None and include_payload and isinstance(proc.payload, dict):
        payload = proc.payload
    payload = payload if isinstance(payload, dict) else {}

    last_step = None
    if isinstance(payload.get("last_step"), dict):
        last_step = str(
            payload["last_step"].get("content") or payload["last_step"].get("nome") or ""
        )
    elif payload.get("last_step_content"):
        last_step = str(payload.get("last_step_content"))

    situacao_raw = proc.situacao
    # Se capa veio como "---", resolve pelo payload / última movimentação
    use_payload = payload if (payload and is_placeholder_status(situacao_raw)) else (
        payload if payload else None
    )
    situacao_full, situacao_key = resolve_situacao_oficial(
        situacao_raw,
        payload=use_payload or (payload or None),
        last_movement=last_movement or last_step,
    )
    outcome = classify_outcome(situacao_full if situacao_full != "—" else None, last_step=last_step)
    # Extinto / arquivado → encerrado
    if situacao_key in ("extinto", "arquivado", "baixado"):
        outcome = "encerrado"
    elif situacao_key == "em_grau_de_recurso":
        outcome = "ativo"

    tribunal = proc.tribunal or "N/D"
    crits = criteria_labels or ["—"]
    crits_sorted = sorted(crits, key=lambda c: (0 if c.startswith("OAB ") else 1, c))

    return {
        "id": proc.id,
        "numero_cnj": proc.numero_cnj,
        "tribunal": tribunal,
        "classe": proc.classe or "—",
        "assunto": proc.assunto or "—",
        "situacao": situacao_full,
        "situacao_short": _truncate(situacao_full, 120),
        "situacao_key": situacao_key,
        "outcome": outcome,
        "grau": proc.grau or "—",
        "orgao_julgador": proc.orgao_julgador or "—",
        "data_distribuicao": _fmt_dt(proc.data_distribuicao),
        "last_checked_at": _fmt_dt(proc.last_checked_at),
        "last_movement_at": _fmt_dt(proc.last_movement_at),
        "criteria": ", ".join(crits_sorted),
        "criteria_list": crits_sorted,
        "baseline": proc.baseline,
        "official_link": resolve_official_link(
            proc.numero_cnj,
            tribunal=tribunal,
            payload=payload if payload else None,
        ),
    }


def build_portfolio(session: Session, *, include_processes: bool = True) -> dict[str, Any]:
    """Portfólio completo (e-mail/digest). Para UI, preferir `build_portfolio_stats`."""
    if not include_processes:
        return build_portfolio_stats(session)

    processes = list(
        session.scalars(
            select(Process).order_by(
                Process.last_movement_at.desc().nulls_last(),
                Process.numero_cnj.asc(),
            )
        ).all()
    )
    criteria, process_criteria = load_process_criteria(session)

    by_oab: Counter[str] = Counter()
    by_tribunal: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []

    for proc in processes:
        crits = process_criteria.get(proc.id) or ["—"]
        row = serialize_process_row(proc, criteria_labels=crits, include_payload=True)
        by_outcome[row["outcome"]] += 1
        by_tribunal[row["tribunal"]] += 1
        for c in row["criteria_list"]:
            if c.startswith("OAB "):
                by_oab[c] += 1
        rows.append(row)

    _include_all_oab_criteria(criteria, by_oab)

    return _stats_from_counters(
        total=len(processes),
        by_outcome=by_outcome,
        by_oab=by_oab,
        by_tribunal=by_tribunal,
        oab_criteria_count=sum(1 for c in criteria.values() if c.criterion_type == "OAB"),
        processes=rows,
    )
