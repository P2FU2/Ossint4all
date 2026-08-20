"""OSINT4ALL HTML/PDF com citações, verificação e anexos."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from io import BytesIO
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from osint4all.config import get_settings
from osint4all.db.models import CaseNote, CaseTask, Edge, Entity, Evidence, Investigation
from osint4all.graph.identity import entity_status
from osint4all.paths import project_root
from osint4all.quality.verification import verdict_label
from osint4all.security import mask_identifier


def _stamp(value: datetime | None) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def _ai_summary(inv: Investigation, entities: list[Entity], evidence: list[Evidence], edges: list[Edge]) -> str:
    settings = get_settings()
    fallback = (
        f"Investigação «{inv.title}» com {len(entities)} entidades, {len(edges)} vínculos e {len(evidence)} evidências. "
        "Cada afirmação abaixo deve ser lida com a citação da fonte. "
        "Nome sozinho não confirma identidade; CPF/CNPJ/CNJ são identificadores fortes."
    )
    if not settings.openrouter_api_key:
        return fallback
    cites = []
    for idx, ev in enumerate(evidence[:24], start=1):
        cites.append(f"[{idx}] {ev.source_label}: {(ev.snippet or ev.url or ev.connector)[:180]}")
    try:
        from openai import OpenAI

        client = OpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)
        names = ", ".join(f"{e.display_name} ({entity_status(e)})" for e in entities[:24])
        resp = client.chat.completions.create(
            model=settings.openrouter_model,
            timeout=settings.openrouter_timeout_seconds,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Resuma um dossiê jornalístico em português. "
                        "Só use o que as evidências numeradas mostram. "
                        "Cada frase termina com [n]. Sem especulação. Sem inventar fonte."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Título: {inv.title}\nHipótese: {inv.hypothesis or '—'}\n"
                        f"Finalidade: {inv.purpose or '—'}\n"
                        f"Entidades: {names}\nVínculos: {len(edges)}\nEvidências:\n" + "\n".join(cites)
                    ),
                },
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return fallback
        allowed = {f"[{i}]" for i in range(1, min(len(evidence), 24) + 1)}
        if "[" in text and not any(mark in text for mark in allowed):
            return fallback
        return text
    except Exception:
        return fallback


def _attachments(investigation_id: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for folder in (
        project_root() / "data" / "uploads" / investigation_id,
        project_root() / "data" / "captures" / investigation_id,
    ):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file():
                rows.append((path.name, str(path.relative_to(project_root())).replace("\\", "/")))
    return rows[:40]


def render_dossier_html(session: Session, investigation_id: str) -> str:
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return "<html><body>Investigação não encontrada.</body></html>"
    entities = list(
        session.scalars(
            select(Entity)
            .options(selectinload(Entity.identifiers), selectinload(Entity.evidence))
            .where(Entity.investigation_id == investigation_id)
        ).all()
    )
    edges = list(session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)).all())
    evidence = list(
        session.scalars(
            select(Evidence).where(Evidence.investigation_id == investigation_id).order_by(Evidence.collected_at)
        ).all()
    )
    notes = list(session.scalars(select(CaseNote).where(CaseNote.investigation_id == investigation_id)).all())
    tasks = list(session.scalars(select(CaseTask).where(CaseTask.investigation_id == investigation_id)).all())
    by_id = {e.id: e for e in entities}
    cite_of = {ev.id: idx for idx, ev in enumerate(evidence, start=1)}
    summary = _ai_summary(inv, entities, evidence, edges)
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    from osint4all.engines.verification import quality_score

    quality = quality_score(session, inv)

    rows = []
    for e in entities:
        ids = [f"{ident.kind}: {escape(mask_identifier(ident.kind, ident.value))}" for ident in e.identifiers]
        cites = ", ".join(f"[{cite_of[ev.id]}]" for ev in (e.evidence or []) if ev.id in cite_of) or "—"
        rows.append(
            f"<tr><td>{escape(e.entity_type)}</td><td>{escape(e.display_name)}</td>"
            f"<td>{escape(', '.join(ids))}</td><td>{escape(verdict_label(entity_status(e)))}</td>"
            f"<td>{e.confidence:.2f}</td><td>{cites}</td></tr>"
        )
    links = []
    for edge in edges:
        src = by_id.get(edge.from_entity_id)
        dst = by_id.get(edge.to_entity_id)
        if not src or not dst:
            continue
        links.append(
            f"<tr><td>{escape(src.display_name)}</td><td>{escape(edge.rel_type)}</td>"
            f"<td>{escape(dst.display_name)}</td><td>{escape(edge.source_connector or '')}</td></tr>"
        )
    ev_rows = []
    for idx, ev in enumerate(evidence, start=1):
        ev_rows.append(
            f"<tr><td>[{idx}]</td><td>{escape(ev.source_label)}</td>"
            f"<td>{escape(ev.method or 'GET')}</td><td>{ev.http_status or '—'}</td>"
            f"<td>{_stamp(ev.collected_at)}</td><td>{escape(ev.content_sha256 or ev.dedup_hash)[:16]}</td>"
            f"<td>{escape(ev.url or '')}</td><td>{escape((ev.snippet or '')[:240])}</td></tr>"
        )
    note_rows = "".join(
        f"<tr><td>{escape(n.title)}</td><td>{escape((n.body or '')[:300])}</td><td>{escape(n.created_by or '')}</td></tr>"
        for n in notes
    ) or "<tr><td colspan='3'>Nenhuma anotação.</td></tr>"
    task_rows = "".join(
        f"<tr><td>{escape(t.title)}</td><td>{escape(t.status)}</td><td>{escape(t.assignee or '')}</td></tr>"
        for t in tasks
    ) or "<tr><td colspan='3'>Nenhuma tarefa.</td></tr>"
    att_rows = "".join(
        f"<tr><td>{escape(name)}</td><td><code>{escape(rel)}</code></td></tr>" for name, rel in _attachments(inv.id)
    ) or "<tr><td colspan='2'>Nenhum anexo local.</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <title>OSINT4ALL — {escape(inv.title)}</title>
  <style>
    body {{ font-family: Georgia, serif; color: #111; margin: 32px; }}
    h1, h2 {{ font-family: Helvetica, Arial, sans-serif; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f1ea; }}
    .meta {{ color: #555; }}
    .disclaimer {{ font-size: 11px; color: #666; margin-top: 24px; }}
  </style>
</head>
<body>
  <h1>OSINT4ALL — {escape(inv.title)}</h1>
  <p class="meta">
    Caso {escape(inv.id)} · Gerado em {escape(generated)} · Responsável: {escape(inv.assignee or inv.created_by or "—")}<br/>
    Hipótese: {escape(inv.hypothesis or "—")}<br/>
    Finalidade: {escape(inv.purpose or "jornalismo investigativo")}<br/>
    Classificação: {escape(inv.classification or "interno")} · Estado: {escape(inv.status)} ·
    Retenção: {_stamp(inv.retain_until)}
  </p>
  <h2>Qualidade do dossiê · {quality["overall"]}/100</h2>
  <p>
    Cobertura {quality["source_coverage"]}% · Primárias {quality["primary_sources"]}% ·
    Verificadas {quality["claims_verified"]}% · Contradições {quality["contradictions_open"]} ·
    Evidência velha {quality["stale_evidence"]}% · Origens independentes {quality["independent_origins"]}
  </p>
  <h2>Síntese</h2>
  <p>{escape(summary)}</p>
  <h2>Entidades ({len(entities)})</h2>
  <table>
    <tr><th>Tipo</th><th>Nome</th><th>Identificadores</th><th>Veredito</th><th>Confiança</th><th>Citações</th></tr>
    {''.join(rows)}
  </table>
  <h2>Vínculos ({len(edges)})</h2>
  <table>
    <tr><th>De</th><th>Relação</th><th>Para</th><th>Fonte</th></tr>
    {''.join(links)}
  </table>
  <h2>Evidências ({len(evidence)})</h2>
  <table>
    <tr><th>#</th><th>Fonte</th><th>Método</th><th>HTTP</th><th>Coletado</th><th>Hash</th><th>URL</th><th>Trecho</th></tr>
    {''.join(ev_rows)}
  </table>
  <h2>Anotações</h2>
  <table><tr><th>Título</th><th>Texto</th><th>Autor</th></tr>{note_rows}</table>
  <h2>Tarefas</h2>
  <table><tr><th>Tarefa</th><th>Estado</th><th>Responsável</th></tr>{task_rows}</table>
  <h2>Anexos</h2>
  <table><tr><th>Arquivo</th><th>Caminho</th></tr>{att_rows}</table>
  <p class="disclaimer">
    Material para jornalismo investigativo. Só fontes públicas e oficiais.
    Cada evidência tem fonte, data, método e hash. Não substitui certidão oficial.
    Não inclui bases restritas (DETRAN, cartório, operadora) nem conteúdo privado de redes sociais.
    Reproduza a conclusão pelas citações [n].
  </p>
</body>
</html>
"""


def render_dossier_pdf(session: Session, investigation_id: str) -> bytes:
    html = render_dossier_html(session, investigation_id)
    from xhtml2pdf import pisa

    buf = BytesIO()
    pisa.CreatePDF(html, dest=buf)
    return buf.getvalue()
