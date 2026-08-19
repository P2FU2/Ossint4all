"""OSINT4ALL HTML/PDF com citações de fonte."""

from __future__ import annotations

from html import escape
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from osint4all.config import get_settings
from osint4all.db.models import Edge, Entity, Evidence, Investigation
from osint4all.security import mask_identifier


def _ai_summary(inv: Investigation, entities: list[Entity], edges: list[Edge]) -> str:
    settings = get_settings()
    fallback = (
        f"Investigação «{inv.title}» com {len(entities)} entidades e {len(edges)} vínculos. "
        "Todos os nós abaixo vieram de fontes públicas ou oficiais citadas. "
        "Nome sozinho não confirma identidade; CPF/CNPJ/CNJ são identificadores fortes."
    )
    if not settings.openrouter_api_key:
        return fallback
    try:
        from openai import OpenAI

        client = OpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)
        names = ", ".join(e.display_name for e in entities[:30])
        resp = client.chat.completions.create(
            model=settings.openrouter_model,
            timeout=settings.openrouter_timeout_seconds,
            messages=[
                {
                    "role": "system",
                    "content": "Resuma um dossiê OSINT jornalístico em português, só com o que as fontes públicas mostram. Sem especulação.",
                },
                {
                    "role": "user",
                    "content": f"Título: {inv.title}\nHipótese: {inv.hypothesis or '—'}\nEntidades: {names}\nVínculos: {len(edges)}",
                },
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or fallback
    except Exception:
        return fallback


def render_dossier_html(session: Session, investigation_id: str) -> str:
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return "<html><body>Investigação não encontrada.</body></html>"
    entities = session.scalars(
        select(Entity)
        .options(selectinload(Entity.identifiers))
        .where(Entity.investigation_id == investigation_id)
    ).all()
    edges = session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)).all()
    evidence = session.scalars(select(Evidence).where(Evidence.investigation_id == investigation_id)).all()
    by_id = {e.id: e for e in entities}
    summary = _ai_summary(inv, list(entities), list(edges))

    rows = []
    for e in entities:
        ids = []
        for ident in e.identifiers:
            ids.append(f"{ident.kind}: {escape(mask_identifier(ident.kind, ident.value))}")
        rows.append(
            f"<tr><td>{escape(e.entity_type)}</td><td>{escape(e.display_name)}</td>"
            f"<td>{escape(', '.join(ids))}</td><td>{e.confidence:.2f}</td></tr>"
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
    for ev in evidence:
        ev_rows.append(
            f"<tr><td>{escape(ev.connector)}</td><td>{escape(ev.source_label)}</td>"
            f"<td>{escape(ev.url or '')}</td><td>{escape((ev.snippet or '')[:240])}</td></tr>"
        )

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
  <p class="meta">Hipótese: {escape(inv.hypothesis or "—")}<br/>
  Profundidade: {inv.max_depth} · Conectores: {escape(", ".join(inv.connectors or []))}</p>
  <h2>Síntese</h2>
  <p>{escape(summary)}</p>
  <h2>Entidades ({len(entities)})</h2>
  <table>
    <tr><th>Tipo</th><th>Nome</th><th>Identificadores</th><th>Confiança</th></tr>
    {''.join(rows)}
  </table>
  <h2>Vínculos ({len(edges)})</h2>
  <table>
    <tr><th>De</th><th>Relação</th><th>Para</th><th>Fonte</th></tr>
    {''.join(links)}
  </table>
  <h2>Evidências ({len(evidence)})</h2>
  <table>
    <tr><th>Conector</th><th>Fonte</th><th>URL</th><th>Trecho</th></tr>
    {''.join(ev_rows)}
  </table>
  <p class="disclaimer">
    Material para jornalismo investigativo. Dados provenientes de APIs e páginas públicas.
    Não substitui certidão oficial. Não inclui bases restritas (DETRAN, cartório, operadora)
    nem conteúdo privado de redes sociais.
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
