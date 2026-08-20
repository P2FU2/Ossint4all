"""Histórico de consultas do usuário — sem guardar o dump completo."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from osint4all.consult import KIND_LABELS, MODES
from osint4all.db.models import SearchHistory, User

_CONSULT_MODES = {key for key, *_ in MODES}
_TOOL_MODES = {
    "plate": "PLATE",
    "phone": "PHONE",
    "name": "NAME",
    "cnpj": "CNPJ",
    "cpf": "CPF",
    "email": "EMAIL",
    "cnj": "CNJ",
    "username": "USERNAME",
    "massa": "massa",
    "mass": "massa",
}
_PANEL_TOOLS = frozenset({"crtsh", "web", "pdf"})
_KIND_TOOLS = {"URL": "crtsh", "FILE": "pdf"}
_EXTRA_LABELS = {
    "massa": "Massa",
    "crtsh": "Certificados",
    "web": "Menções web",
    "pdf": "PDF",
}

KEEP_PER_USER = 80
SHOW_LIMIT = 24


def record_search(
    session: Session,
    user: User,
    *,
    query: str,
    mode: str = "auto",
    kind: str = "",
    title: str = "",
    summary: str = "",
    ok: bool = True,
) -> SearchHistory | None:
    text = (query or "").strip()
    if not text:
        return None
    mode = (mode or "auto")[:32]
    last = session.scalar(
        select(SearchHistory)
        .where(SearchHistory.user_id == user.id)
        .order_by(desc(SearchHistory.created_at))
        .limit(1)
    )
    if last and last.query.casefold() == text.casefold() and (last.mode or "") == mode:
        last.kind = (kind or last.kind or "")[:32]
        last.title = (title or text)[:255]
        last.summary = (summary or "")[:400]
        last.ok = ok
        last.created_at = datetime.now(timezone.utc)
        session.flush()
        return last
    row = SearchHistory(
        user_id=user.id,
        username=user.username,
        mode=mode,
        kind=(kind or "")[:32],
        query=text[:512],
        title=(title or text)[:255],
        summary=(summary or "")[:400],
        ok=ok,
    )
    session.add(row)
    session.flush()
    old_ids = list(
        session.scalars(
            select(SearchHistory.id)
            .where(SearchHistory.user_id == user.id)
            .order_by(desc(SearchHistory.created_at))
            .offset(KEEP_PER_USER)
        )
    )
    if old_ids:
        session.execute(delete(SearchHistory).where(SearchHistory.id.in_(old_ids)))
    return row


def list_searches(session: Session, user: User, *, limit: int = SHOW_LIMIT) -> list[SearchHistory]:
    return list(
        session.scalars(
            select(SearchHistory)
            .where(SearchHistory.user_id == user.id)
            .order_by(desc(SearchHistory.created_at))
            .limit(limit)
        )
    )


def clear_searches(session: Session, user: User) -> int:
    result = session.execute(delete(SearchHistory).where(SearchHistory.user_id == user.id))
    return int(result.rowcount or 0)


def kind_label(kind: str) -> str:
    if kind in _EXTRA_LABELS:
        return _EXTRA_LABELS[kind]
    return KIND_LABELS.get(kind, kind or "consulta")


def replay_mode(mode: str, kind: str = "") -> str:
    if mode in _CONSULT_MODES:
        return mode
    mapped = _TOOL_MODES.get((mode or "").lower())
    if mapped:
        return mapped
    if kind in _CONSULT_MODES:
        return kind
    return kind or "auto"


def replay_spec(mode: str, kind: str = "") -> dict[str, str]:
    raw = (mode or "").lower()
    if raw in _PANEL_TOOLS:
        return {"action": "/app/ferramentas/executar", "tool": raw, "mode": replay_mode(mode, kind)}
    kind_tool = _KIND_TOOLS.get((kind or "").upper()) or _KIND_TOOLS.get((mode or "").upper())
    if kind_tool:
        return {"action": "/app/ferramentas/executar", "tool": kind_tool, "mode": replay_mode(mode, kind)}
    return {"action": "/app/consultar", "tool": "", "mode": replay_mode(mode, kind)}
