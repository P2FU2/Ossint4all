"""Geração de HTML do digest."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import Event
from monitor_jus.models import EventType, Priority


SECTION_ORDER = [
    ("Processos descobertos", EventType.PROCESSO_DESCOBERTO.value),
    ("Movimentações processuais", EventType.MOVIMENTACAO_PROCESSUAL.value),
    ("Publicações DJEN", EventType.PUBLICACAO_DJEN.value),
    ("Intimações processuais", EventType.INTIMACAO_PROCESSUAL.value),
    ("Outras comunicações", EventType.COMUNICACAO_OUTRA.value),
    ("Informações atualizadas pela fonte", EventType.EVENTO_CORRIGIDO.value),
]


def build_coverage(settings: Settings) -> list[dict[str, Any]]:
    flags = settings.judit_flags()
    rows = [
        {"label": "Movimentações / lawsuits — Judit", "enabled": True, "reason": ""},
        {
            "label": "Descoberta por OAB — Judit",
            "enabled": flags["oab"] and flags["historical_search"],
            "reason": "desabilitada",
        },
        {
            "label": "Descoberta por CPF/CNPJ — Judit",
            "enabled": flags["cpf_cnpj"] and flags["historical_search"],
            "reason": "desabilitada",
        },
        {
            "label": "Busca por nome — Judit",
            "enabled": flags["name"],
            "reason": "desabilitada",
        },
        {
            "label": "Tracking de processos — Judit",
            "enabled": flags["process_tracking"],
            "reason": "não contratado / desabilitado",
        },
        {
            "label": "Diários e publicações (DJEN) — Judit",
            "enabled": flags["djen"],
            "reason": "não contratados",
        },
        {
            "label": "Confirmação oficial — DataJud",
            "enabled": settings.datajud_enable and settings.datajud_mode != "off",
            "reason": "desabilitada",
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


def render_digest_html(
    events: list[Event],
    *,
    quarantine_count: int = 0,
    skipped: list[str] | None = None,
    failures: list[str] | None = None,
    settings: Settings | None = None,
    zero: bool = False,
) -> str:
    settings = settings or get_settings()
    templates_dir = Path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    coverage = build_coverage(settings)
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    if zero or not events:
        tmpl = env.get_template("email_zero_results.html")
        return tmpl.render(
            generated_at=generated_at,
            tz=settings.tz,
            coverage=coverage,
        )

    urgent = [e for e in events if e.priority == Priority.ALTA.value]
    sections = []
    for title, etype in SECTION_ORDER:
        items = [e for e in events if e.event_type == etype and e.priority != Priority.ALTA.value]
        # urgentes já listados; ainda incluímos nas seções se quiser — plano: urgentes separados
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
        coverage=coverage,
        quarantine_count=quarantine_count,
        totals_by_tribunal=totals_by_tribunal,
        skipped=skipped or [],
        failures=failures or [],
    )
