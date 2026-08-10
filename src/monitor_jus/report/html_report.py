"""Geração de HTML do digest."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import Event
from monitor_jus.models import EventType, Priority
from monitor_jus.official_portal import (
    _is_useless_portal_url,
    resolve_official_link_result,
)

_RE_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")


def format_summary_html(text: str | None) -> Markup:
    """Converte **negrito** markdown em <strong> (escapando o resto)."""
    raw = (text or "").strip()
    if not raw:
        return Markup("")
    escaped = html.escape(raw)
    converted = _RE_MD_BOLD.sub(r"<strong>\1</strong>", escaped)
    return Markup(converted)


SECTION_ORDER = [
    ("Processos descobertos", EventType.PROCESSO_DESCOBERTO.value),
    ("Movimentações processuais", EventType.MOVIMENTACAO_PROCESSUAL.value),
    ("Publicações DJEN", EventType.PUBLICACAO_DJEN.value),
    ("Intimações processuais", EventType.INTIMACAO_PROCESSUAL.value),
    ("Outras comunicações", EventType.COMUNICACAO_OUTRA.value),
    ("Informações atualizadas pela fonte", EventType.EVENTO_CORRIGIDO.value),
]

OUTCOME_LABELS = {
    "ativo": "Em tramitação",
    "exito": "Êxito (estimado)",
    "derrota": "Desfecho desfavorável (estimado)",
    "encerrado": "Encerrado / arquivado",
    "indefinido": "Sem status claro",
}


def build_coverage(settings: Settings) -> list[dict[str, Any]]:
    rows = [
        {
            "label": "Busca nacional por critérios — DJEN",
            "enabled": settings.djen_enable,
            "reason": "desabilitada",
        },
        {
            "label": "Sweep complementar por tribunal — DJEN",
            "enabled": settings.djen_enable,
            "reason": "desabilitada",
        },
        {
            "label": "Enriquecimento de capa/movimentos — DataJud",
            "enabled": settings.datajud_enable and settings.datajud_mode != "off",
            "reason": "desabilitada",
        },
        {
            "label": "Validação CNA",
            "enabled": settings.cna_enabled,
            "reason": "desabilitada (fora do caminho crítico)",
        },
        {
            "label": "Resumo por IA — OpenRouter",
            "enabled": bool(settings.openrouter_api_key),
            "reason": "indisponível",
        },
        {
            "label": "Envio de e-mail — Resend",
            "enabled": bool(settings.resend_api_key),
            "reason": "indisponível",
        },
    ]
    return rows


def recent_source_failures(session=None, *, hours: int = 48) -> list[dict[str, Any]]:
    """Falhas parciais de fontes para o digest."""
    if session is None:
        return []
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from monitor_jus.db.models import Criterion, SourceRun

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = list(
        session.scalars(
            select(SourceRun)
            .where(SourceRun.status == "FAILED", SourceRun.started_at >= cutoff)
            .order_by(SourceRun.started_at.desc())
            .limit(20)
        ).all()
    )
    crit_ids = {r.criteria_id for r in rows if r.criteria_id}
    crit_labels: dict[str, str] = {}
    if crit_ids:
        for c in session.scalars(select(Criterion).where(Criterion.id.in_(crit_ids))).all():
            crit_labels[c.id] = f"{c.criterion_type}:{c.value}"
    out: list[dict[str, Any]] = []
    for r in rows:
        criterion = crit_labels.get(r.criteria_id or "", "")
        out.append(
            {
                "job_type": r.job_type or "—",
                "source": r.source,
                "court": r.court or "—",
                "criterion": criterion or "—",
                "criteria_id": r.criteria_id,
                "error": (r.error_message or r.error_code or "falha")[:200],
            }
        )
    return out


def render_digest_html(
    events: list[Event],
    *,
    quarantine_count: int = 0,
    skipped: list[str] | None = None,
    failures: list[str] | None = None,
    settings: Settings | None = None,
    zero: bool = False,
    portfolio: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
) -> str:
    """HTML do digest — somente novidades (portfolio ignorado)."""
    settings = settings or get_settings()
    templates_dir = Path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["md_bold"] = format_summary_html
    _ = portfolio  # legado: e-mail não inclui mais acervo
    generated_at = datetime.now().strftime("%d/%m/%Y · atualizado às %H:%M")

    def _fmt_change_date(e: Event) -> str:
        raw = getattr(e, "occurred_at", None) or getattr(e, "created_at", None)
        if not raw:
            return ""
        try:
            return raw.astimezone().strftime("%d/%m/%Y %H:%M")
        except Exception:  # noqa: BLE001
            return str(raw)[:16]

    def _change_label(e: Event) -> str:
        if e.event_type == EventType.MOVIMENTACAO_PROCESSUAL.value:
            return "Movimentação em"
        if e.event_type == EventType.PUBLICACAO_DJEN.value:
            return "Publicação em"
        if getattr(e, "occurred_at", None):
            return "Alteração em"
        return "Detectado em"

    for e in events:
        existing = e.official_link
        if _is_useless_portal_url(existing):
            existing = None
        link = resolve_official_link_result(
            e.numero_cnj,
            tribunal=e.tribunal,
            existing=existing,
            classe=None,
            grau=None,
        )
        if link.url and link.link_type not in {"UNAVAILABLE", "COURT_HOMEPAGE"}:
            e.official_link = link.url
        elif link.url and (not e.official_link or _is_useless_portal_url(e.official_link)):
            e.official_link = link.url
        # Campos só para o template (não persistem)
        e.change_date_label = _change_label(e)  # type: ignore[attr-defined]
        e.change_date = _fmt_change_date(e)  # type: ignore[attr-defined]

    urgent = [e for e in events if e.priority == Priority.ALTA.value]
    sections = []
    for title, etype in SECTION_ORDER:
        items = [e for e in events if e.event_type == etype]
        sections.append((title, items))

    totals_by_tribunal: dict[str, int] = {}
    for e in events:
        key = e.tribunal or "N/D"
        totals_by_tribunal[key] = totals_by_tribunal.get(key, 0) + 1

    tmpl = env.get_template("email_report.html")
    return tmpl.render(
        generated_at=generated_at,
        tz=settings.tz,
        total=len(events),
        urgent_count=len(urgent),
        urgent=urgent,
        sections=sections,
        quarantine_count=quarantine_count,
        totals_by_tribunal=totals_by_tribunal,
        skipped=skipped or [],
        failures=failures or [],
        source_health=source_health,
        zero=zero or not events,
    )
