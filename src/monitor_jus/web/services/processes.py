"""Acervo e detalhe de processos."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from monitor_jus.db.models import (
    Communication,
    Criterion,
    CriterionLink,
    Event,
    Process,
    ProcessMovement,
)
from monitor_jus.official_portal import resolve_official_link
from monitor_jus.pipeline.portfolio import (
    classify_outcome,
    load_process_criteria,
    serialize_process_row,
)
from monitor_jus.pipeline.status_oficial import (
    SITUACAO_LABELS,
    is_placeholder_status,
    resolve_situacao_oficial,
)
from monitor_jus.security import redact_text

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFAULT_SORT_BY = "last_movement_at"
DEFAULT_SORT_DIR = "desc"

SORT_LABELS: dict[str, str] = {
    "last_movement_at": "Última movimentação",
    "numero_cnj": "CNJ",
    "tribunal": "Tribunal",
    "classe": "Classe / assunto",
    "situacao": "Situação",
    "outcome": "Resultado",
    "criteria": "Critérios",
}

_DT_MIN = datetime.min.replace(tzinfo=timezone.utc)
_DT_MAX = datetime.max.replace(tzinfo=timezone.utc)


def _fmt(dt: Any) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


def _light_processes(session: Session) -> list[Process]:
    """Carrega processos sem coluna payload (JSON pesado)."""
    return list(
        session.scalars(
            select(Process)
            .options(
                load_only(
                    Process.id,
                    Process.numero_cnj,
                    Process.tribunal,
                    Process.classe,
                    Process.assunto,
                    Process.situacao,
                    Process.grau,
                    Process.orgao_julgador,
                    Process.data_distribuicao,
                    Process.last_checked_at,
                    Process.last_movement_at,
                    Process.baseline,
                )
            )
            .order_by(
                Process.last_movement_at.desc().nulls_last(),
                Process.numero_cnj.asc(),
            )
        ).all()
    )


def _normalize_sort(sort_by: str, sort_dir: str) -> tuple[str, str]:
    field = (sort_by or DEFAULT_SORT_BY).strip()
    if field not in SORT_LABELS:
        field = DEFAULT_SORT_BY
    direction = (sort_dir or DEFAULT_SORT_DIR).strip().lower()
    if direction not in ("asc", "desc"):
        direction = DEFAULT_SORT_DIR if field == "last_movement_at" else "asc"
    return field, direction


def _sort_key_fn(sort_by: str, sort_dir: str) -> Callable[[dict[str, Any]], Any]:
    reverse = sort_dir == "desc"

    def dt_key(row: dict[str, Any]) -> datetime:
        val = row.get("_sort_last_movement")
        if isinstance(val, datetime):
            if val.tzinfo is None:
                return val.replace(tzinfo=timezone.utc)
            return val
        # nulls no fim em qualquer direção
        return _DT_MIN if reverse else _DT_MAX

    keys: dict[str, Callable[[dict[str, Any]], Any]] = {
        "last_movement_at": dt_key,
        "numero_cnj": lambda r: (r.get("numero_cnj") or "").lower(),
        "tribunal": lambda r: (r.get("tribunal") or "").lower(),
        "classe": lambda r: ((r.get("classe") or "") + " " + (r.get("assunto") or "")).lower(),
        "situacao": lambda r: (r.get("situacao") or "").lower(),
        "outcome": lambda r: (r.get("outcome") or "").lower(),
        "criteria": lambda r: (r.get("criteria") or "").lower(),
    }
    return keys.get(sort_by) or keys[DEFAULT_SORT_BY]


def sort_process_rows(
    rows: list[dict[str, Any]], *, sort_by: str, sort_dir: str
) -> list[dict[str, Any]]:
    """Ordena o conjunto filtrado inteiro (antes da paginação)."""
    field, direction = _normalize_sort(sort_by, sort_dir)
    key_fn = _sort_key_fn(field, direction)
    return sorted(rows, key=key_fn, reverse=(direction == "desc"))


def build_query_string(filters: dict[str, Any], **overrides: Any) -> str:
    """Query string preservando filtros/ordenação/paginação."""
    data = {
        "q": filters.get("q") or "",
        "tribunal": filters.get("tribunal") or "",
        "oab": filters.get("oab") or "",
        "outcome": filters.get("outcome") or "",
        "situacao": filters.get("situacao") or "",
        "pending_only": "true" if filters.get("pending_only") else "false",
        "sort_by": filters.get("sort_by") or DEFAULT_SORT_BY,
        "sort_dir": filters.get("sort_dir") or DEFAULT_SORT_DIR,
        "page": filters.get("page") or 1,
        "page_size": filters.get("page_size") or DEFAULT_PAGE_SIZE,
    }
    data.update(overrides)
    # remove vazios opcionais (mantém pending_only/sort sempre)
    cleaned = {k: v for k, v in data.items() if v not in ("", None)}
    return urlencode(cleaned)


def _payloads_for_placeholders(
    session: Session, procs: list[Process]
) -> dict[str, dict[str, Any]]:
    """Carrega payload só dos processos com situação vazia/---."""
    need = [p.id for p in procs if is_placeholder_status(p.situacao)]
    if not need:
        return {}
    rows = session.execute(select(Process.id, Process.payload).where(Process.id.in_(need))).all()
    out: dict[str, dict[str, Any]] = {}
    for pid, payload in rows:
        if isinstance(payload, dict):
            out[pid] = payload
    return out


def _filtered_process_rows(
    session: Session,
    *,
    q: str = "",
    tribunal: str = "",
    oab: str = "",
    outcome: str = "",
    situacao: str = "",
    pending_only: bool = False,
    sort_by: str = DEFAULT_SORT_BY,
    sort_dir: str = DEFAULT_SORT_DIR,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Retorna (linhas filtradas e ordenadas no acervo inteiro, tribunais, total_acervo)."""
    _, process_criteria = load_process_criteria(session)
    procs = _light_processes(session)
    payloads = _payloads_for_placeholders(session, procs)

    pending_cnjs: set[str] = set()
    if pending_only:
        pending_cnjs = {
            e.numero_cnj
            for e in session.scalars(
                select(Event.numero_cnj).where(
                    Event.notify_status == "PENDING_NOTIFY",
                    Event.numero_cnj.is_not(None),
                )
            ).all()
            if e
        }

    q_norm = (q or "").strip().lower()
    tribunal_norm = (tribunal or "").strip().lower()
    oab_raw = (oab or "").strip()
    outcome_norm = (outcome or "").strip().lower()
    situacao_norm = (situacao or "").strip().lower()

    from monitor_jus.oab_match import filter_matches_oab_text

    filtered: list[dict[str, Any]] = []
    tribunals: set[str] = set()
    for proc in procs:
        if proc.tribunal:
            tribunals.add(proc.tribunal)
        crits = process_criteria.get(proc.id) or ["—"]
        row = serialize_process_row(
            proc,
            criteria_labels=crits,
            include_payload=False,
            payload=payloads.get(proc.id),
        )
        row["_sort_last_movement"] = proc.last_movement_at

        # Persistência leve: se resolvemos status melhor que "---", grava no banco
        if (
            is_placeholder_status(proc.situacao)
            and row.get("situacao")
            and row["situacao"] != "—"
            and row.get("situacao_key") != "sem_informacao"
        ):
            proc.situacao = row["situacao"]

        if q_norm and q_norm not in row["numero_cnj"].lower() and q_norm not in (row.get("classe") or "").lower():
            if q_norm not in (row.get("assunto") or "").lower():
                continue
        if tribunal_norm and tribunal_norm not in (row.get("tribunal") or "").lower():
            continue
        if oab_raw and not filter_matches_oab_text(oab_raw, row.get("criteria") or ""):
            continue
        if outcome_norm and row.get("outcome") != outcome_norm:
            continue
        if situacao_norm and row.get("situacao_key") != situacao_norm:
            continue
        if pending_only and row["numero_cnj"] not in pending_cnjs:
            continue
        filtered.append(row)

    field, direction = _normalize_sort(sort_by, sort_dir)
    filtered = sort_process_rows(filtered, sort_by=field, sort_dir=direction)
    return filtered, sorted(tribunals), len(procs)


def list_processes(
    session: Session,
    *,
    q: str = "",
    tribunal: str = "",
    oab: str = "",
    outcome: str = "",
    situacao: str = "",
    pending_only: bool = False,
    sort_by: str = DEFAULT_SORT_BY,
    sort_dir: str = DEFAULT_SORT_DIR,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    sort_by, sort_dir = _normalize_sort(sort_by, sort_dir)

    filtered, tribunals, total_all = _filtered_process_rows(
        session,
        q=q,
        tribunal=tribunal,
        oab=oab,
        outcome=outcome,
        situacao=situacao,
        pending_only=pending_only,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    page_rows = filtered[start : start + page_size]

    filters = {
        "q": q,
        "tribunal": tribunal,
        "oab": oab,
        "outcome": outcome,
        "situacao": situacao,
        "pending_only": pending_only,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "page_size": page_size,
    }

    # URLs de cabeçalho: mesmo campo inverte direção; outro campo inicia com default
    header_sorts: dict[str, dict[str, str]] = {}
    for field in SORT_LABELS:
        if field == sort_by:
            next_dir = "asc" if sort_dir == "desc" else "desc"
        else:
            next_dir = "desc" if field == "last_movement_at" else "asc"
        header_sorts[field] = {
            "sort_by": field,
            "sort_dir": next_dir,
            "active": field == sort_by,
            "dir": sort_dir if field == sort_by else "",
            "href": "/app/processos?"
            + build_query_string(filters, sort_by=field, sort_dir=next_dir, page=1),
        }

    return {
        "processes": page_rows,
        "total": total,
        "total_all": total_all,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "tribunals": tribunals,
        "situacao_labels": SITUACAO_LABELS,
        "sort_labels": SORT_LABELS,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "header_sorts": header_sorts,
        "qs_export": build_query_string(filters, page=None, page_size=None),
        "qs_prev": build_query_string(filters, page=page - 1) if page > 1 else "",
        "qs_next": build_query_string(filters, page=page + 1) if page < total_pages else "",
        "filters": filters,
    }


def processes_csv(session: Session, **filters: Any) -> str:
    filters.pop("page", None)
    filters.pop("page_size", None)
    all_rows, _, _ = _filtered_process_rows(session, **filters)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "numero_cnj",
            "tribunal",
            "classe",
            "assunto",
            "situacao",
            "situacao_key",
            "outcome",
            "grau",
            "criteria",
            "last_movement_at",
            "official_link",
            "baseline",
        ]
    )
    for r in all_rows:
        writer.writerow(
            [
                r["numero_cnj"],
                r["tribunal"],
                r["classe"],
                r["assunto"],
                r["situacao"],
                r.get("situacao_key") or "",
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

    situacao_full, situacao_key = resolve_situacao_oficial(
        proc.situacao, payload=payload, last_movement=last_step
    )
    if is_placeholder_status(proc.situacao) and situacao_full != "—":
        proc.situacao = situacao_full

    outcome = classify_outcome(situacao_full if situacao_full != "—" else None, last_step=last_step)
    if situacao_key in ("extinto", "arquivado", "baixado"):
        outcome = "encerrado"
    elif situacao_key == "em_grau_de_recurso":
        outcome = "ativo"

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
        "situacao": situacao_full,
        "situacao_key": situacao_key,
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
