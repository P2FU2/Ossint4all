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


_ENTITY_TYPES = {
    "PERSON": "Pessoa",
    "ORG": "Organização",
    "PROFILE": "Perfil",
    "PUBLICATION": "Publicação",
    "NOTE": "Nota",
    "EVENT": "Evento",
    "PLACE": "Local",
}

_ID_KINDS = {
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "email": "E-mail",
    "phone": "Telefone",
    "username": "Utilizador",
    "name": "Nome",
    "birthdate": "Nascimento",
    "rg": "RG",
    "title": "Título",
}

_STATUS_LABELS = {
    "open": "Aberto",
    "active": "Ativo",
    "paused": "Pausado",
    "closed": "Encerrado",
    "archived": "Arquivado",
}

_CLASS_LABELS = {
    "interno": "Uso interno",
    "restrito": "Restrito",
    "publico": "Público",
    "publicavel": "Publicável",
}


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


def _label(mapping: dict[str, str], value: str | None, fallback: str = "—") -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    return mapping.get(raw.lower(), mapping.get(raw, raw))


def _paragraphs(text: str) -> str:
    chunks = [part.strip() for part in (text or "").replace("\r", "").split("\n") if part.strip()]
    if not chunks:
        return "<p class='muted'>Sem síntese disponível.</p>"
    return "".join(f"<p>{escape(part)}</p>" for part in chunks)


def _empty(cols: int, text: str) -> str:
    return f"<tr><td colspan='{cols}' class='empty'>{escape(text)}</td></tr>"


def _url_cell(url: str | None) -> str:
    if not url:
        return "—"
    shown = url if len(url) <= 76 else url[:73] + "…"
    return f'<a href="{escape(url)}">{escape(shown)}</a>'


def _verdict_class(label: str) -> str:
    key = (label or "").lower()
    if "confirmado" in key and "não" not in key:
        return "tag tag-ok"
    if "provável" in key:
        return "tag tag-mid"
    if "contest" in key or "falso" in key:
        return "tag tag-bad"
    return "tag tag-soft"


def _dossier_css(*, for_pdf: bool) -> str:
    frame = """
    @page { size: a4; margin: 16mm 14mm 18mm 14mm; }
    body { font-family: Times-Roman, Georgia, serif; color: #1c1916; font-size: 11pt; line-height: 1.45; margin: 0; }
    .nav { display: none; }
    .canvas { padding: 0; }
    .sheet { width: 100%; background: #fff; padding: 0; border: 0; box-shadow: none; }
    """ if for_pdf else """
    body {
      margin: 0; background: #14110e; color: #1c1916;
      font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
      font-size: 15px; line-height: 1.55;
    }
    .nav {
      position: sticky; top: 0; z-index: 4;
      display: flex; justify-content: space-between; align-items: center; gap: 12px;
      padding: 12px 22px; background: rgba(20,17,14,.92);
      border-bottom: 1px solid rgba(232,214,176,.18); color: #efe6d4;
    }
    .nav a {
      color: #efe6d4; text-decoration: none; font-size: 12px; letter-spacing: .04em;
      text-transform: uppercase; border: 1px solid rgba(232,214,176,.28);
      padding: 7px 12px; border-radius: 999px;
    }
    .nav a:hover { background: #efe6d4; color: #14110e; }
    .nav .brand { letter-spacing: .18em; font-size: 11px; opacity: .72; }
    .canvas { padding: 28px 16px 72px; }
    .sheet {
      max-width: 210mm; margin: 0 auto; background: #f7f1e6;
      padding: 28mm 22mm 22mm; box-shadow: 0 28px 80px rgba(0,0,0,.45);
      border: 1px solid #d8cbb3;
    }
    @media print {
      body { background: #fff; }
      .nav { display: none; }
      .canvas { padding: 0; }
      .sheet { box-shadow: none; border: 0; max-width: none; padding: 12mm; }
    }
    """
    return frame + """
    * { box-sizing: border-box; }
    a { color: #1a4034; }
    h1, h2, h3, .brand, .kicker, .nav, .meta-k, .score-n, th {
      font-family: Helvetica, Arial, sans-serif;
    }
    .kicker {
      letter-spacing: .28em; text-transform: uppercase; font-size: 10px;
      color: #6d5c3d; margin: 0 0 10px;
    }
    .mast { border-bottom: 2px solid #1a4034; padding-bottom: 18px; margin-bottom: 22px; }
    h1 {
      font-size: 28px; line-height: 1.15; margin: 0 0 8px; color: #14110e;
      font-weight: 700; letter-spacing: -.02em;
    }
    .sub { color: #5c564e; font-size: 13px; margin: 0; }
    .badge {
      display: inline-block; border: 1px solid #8a6d2f; color: #6d5c3d;
      font-family: Helvetica, Arial, sans-serif; font-size: 10px; letter-spacing: .12em;
      text-transform: uppercase; padding: 3px 8px; margin-right: 6px;
    }
    .meta-grid { width: 100%; border-collapse: collapse; margin: 18px 0 0; }
    .meta-grid td {
      width: 25%; vertical-align: top; padding: 10px 12px 10px 0;
      border-top: 1px solid #d8cbb3;
    }
    .meta-k {
      display: block; font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
      color: #8a6d2f; margin-bottom: 4px;
    }
    .meta-v { font-size: 14px; color: #1c1916; }
    h2 {
      font-size: 13px; letter-spacing: .16em; text-transform: uppercase;
      color: #1a4034; border-bottom: 1px solid #d8cbb3;
      padding: 0 0 7px; margin: 32px 0 14px; font-weight: 700;
    }
    h2 span { color: #8a6d2f; letter-spacing: .08em; font-weight: 500; }
    .lede {
      background: #efe6d4; border-left: 4px solid #1a4034;
      padding: 14px 18px; margin: 0 0 8px;
    }
    .lede p { margin: 0 0 8px; }
    .lede p:last-child { margin: 0; }
    .scoreboard { width: 100%; border-collapse: collapse; margin: 0; }
    .scoreboard td {
      vertical-align: top; padding: 12px 10px 12px 0;
      border-top: 1px solid #d8cbb3; width: 16.66%;
    }
    .score-n {
      display: block; font-size: 28px; line-height: 1; color: #1a4034; font-weight: 700;
    }
    .score-n small { font-size: 13px; color: #8a6d2f; font-weight: 500; }
    .score-k {
      display: block; font-size: 10px; letter-spacing: .08em;
      text-transform: uppercase; color: #6d5c3d; margin-top: 6px;
    }
    table.data { border-collapse: collapse; width: 100%; font-size: 12px; }
    table.data th, table.data td {
      border-bottom: 1px solid #e0d4be; padding: 8px 7px; text-align: left; vertical-align: top;
    }
    table.data th {
      background: #1a4034; color: #f7f1e6; font-size: 10px; letter-spacing: .08em;
      text-transform: uppercase; font-weight: 600; border-bottom: 0;
    }
    table.data tr:nth-child(even) td { background: #f1eadc; }
    .name { font-weight: 700; }
    .ids, .hash, .url { word-break: break-word; font-size: 11px; color: #3f3a34; }
    .cites, .cite {
      font-family: Helvetica, Arial, sans-serif; color: #1a4034; font-weight: 700; white-space: nowrap;
    }
    .rel { font-style: italic; color: #3f3a34; }
    .empty, .muted { color: #6d5c3d; font-style: italic; }
    .tag {
      display: inline-block; font-family: Helvetica, Arial, sans-serif;
      font-size: 10px; letter-spacing: .04em; padding: 2px 7px; border: 1px solid #c4b8a4;
    }
    .tag-ok { background: #dce8df; border-color: #1a4034; color: #1a4034; }
    .tag-mid { background: #efe6d4; border-color: #8a6d2f; color: #6d5c3d; }
    .tag-soft { background: #eeeae2; color: #5c564e; }
    .tag-bad { background: #f3ddd6; border-color: #8a3b2f; color: #8a3b2f; }
    .disclaimer {
      margin-top: 36px; padding-top: 14px; border-top: 2px solid #1a4034;
      font-size: 11px; color: #5c564e; line-height: 1.5;
    }
    .foot {
      margin-top: 18px; font-family: Helvetica, Arial, sans-serif;
      font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: #8a6d2f;
    }
    """


def render_dossier_html(session: Session, investigation_id: str, *, for_pdf: bool = False) -> str:
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
        ids = [
            f"{_label(_ID_KINDS, ident.kind, ident.kind)} {mask_identifier(ident.kind, ident.value)}"
            for ident in e.identifiers
        ]
        cites = " ".join(f"[{cite_of[ev.id]}]" for ev in (e.evidence or []) if ev.id in cite_of) or "—"
        verdict = verdict_label(entity_status(e))
        ids_html = "<br/>".join(escape(item) for item in ids) if ids else "—"
        rows.append(
            f"<tr><td>{escape(_label(_ENTITY_TYPES, e.entity_type, e.entity_type))}</td>"
            f"<td class='name'>{escape(e.display_name)}</td>"
            f"<td class='ids'>{ids_html}</td>"
            f"<td><span class='{_verdict_class(verdict)}'>{escape(verdict)}</span></td>"
            f"<td>{e.confidence:.0%}</td><td class='cites'>{cites}</td></tr>"
        )
    links = []
    for edge in edges:
        src = by_id.get(edge.from_entity_id)
        dst = by_id.get(edge.to_entity_id)
        if not src or not dst:
            continue
        rel = (edge.rel_type or "").replace("_", " ").strip() or "—"
        links.append(
            f"<tr><td class='name'>{escape(src.display_name)}</td>"
            f"<td class='rel'>{escape(rel)}</td>"
            f"<td class='name'>{escape(dst.display_name)}</td>"
            f"<td>{escape(edge.source_connector or '—')}</td></tr>"
        )
    ev_rows = []
    for idx, ev in enumerate(evidence, start=1):
        ev_rows.append(
            f"<tr><td class='cite'>[{idx}]</td><td>{escape(ev.source_label)}</td>"
            f"<td>{escape(ev.method or 'GET')}</td><td>{ev.http_status or '—'}</td>"
            f"<td>{_stamp(ev.collected_at)}</td><td class='hash'>{escape((ev.content_sha256 or ev.dedup_hash or '—')[:16])}</td>"
            f"<td class='url'>{_url_cell(ev.url)}</td>"
            f"<td>{escape((ev.snippet or '')[:240]) or '—'}</td></tr>"
        )
    note_rows = "".join(
        f"<tr><td class='name'>{escape(n.title)}</td><td>{escape((n.body or '')[:400])}</td>"
        f"<td>{escape(n.created_by or '—')}</td></tr>"
        for n in notes
    ) or _empty(3, "Nenhuma anotação.")
    task_rows = "".join(
        f"<tr><td class='name'>{escape(t.title)}</td><td>{escape(_label(_STATUS_LABELS, t.status, t.status))}</td>"
        f"<td>{escape(t.assignee or '—')}</td></tr>"
        for t in tasks
    ) or _empty(3, "Nenhuma tarefa.")
    att_rows = "".join(
        f"<tr><td>{escape(name)}</td><td class='hash'>{escape(rel)}</td></tr>" for name, rel in _attachments(inv.id)
    ) or _empty(2, "Nenhum anexo local.")

    classification = inv.classification or "interno"
    status = _label(_STATUS_LABELS, inv.status, inv.status or "—")
    purpose = inv.purpose or "jornalismo investigativo"
    owner = inv.assignee or inv.created_by or "—"
    score = int(quality.get("overall") or 0)
    nav = ""
    if not for_pdf:
        nav = (
            '<nav class="nav"><span class="brand">OSINT4ALL · Dossiê</span><span>'
            f'<a href="/app/casos/{escape(inv.id)}">Voltar ao caso</a> '
            f'<a href="/app/casos/{escape(inv.id)}/relatorio.pdf">Baixar PDF</a>'
            "</span></nav>"
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OSINT4ALL — {escape(inv.title)}</title>
  <style>{_dossier_css(for_pdf=for_pdf)}</style>
</head>
<body>
  {nav}
  <div class="canvas">
  <article class="sheet">
    <header class="mast">
      <p class="kicker">OSINT4ALL · Relatório de investigação</p>
      <h1>{escape(inv.title)}</h1>
      <p class="sub">
        <span class="badge">{escape(_label(_CLASS_LABELS, classification, classification))}</span>
        Caso {escape(inv.id)} · Gerado em {escape(generated)} · Responsável: {escape(owner)}
      </p>
      <table class="meta-grid">
        <tr>
          <td><span class="meta-k">Hipótese</span><span class="meta-v">{escape(inv.hypothesis or "—")}</span></td>
          <td><span class="meta-k">Finalidade</span><span class="meta-v">{escape(purpose)}</span></td>
          <td><span class="meta-k">Estado</span><span class="meta-v">{escape(status)}</span></td>
          <td><span class="meta-k">Retenção</span><span class="meta-v">{_stamp(inv.retain_until)}</span></td>
        </tr>
      </table>
    </header>

    <h2>Qualidade do dossiê</h2>
    <table class="scoreboard">
      <tr>
        <td><span class="score-n">{score}<small>/100</small></span><span class="score-k">Índice geral</span></td>
        <td><span class="score-n">{quality["source_coverage"]}%</span><span class="score-k">Cobertura</span></td>
        <td><span class="score-n">{quality["primary_sources"]}%</span><span class="score-k">Primárias</span></td>
        <td><span class="score-n">{quality["claims_verified"]}%</span><span class="score-k">Verificadas</span></td>
        <td><span class="score-n">{quality["independent_origins"]}</span><span class="score-k">Origens independentes</span></td>
        <td><span class="score-n">{quality["contradictions_open"]}</span><span class="score-k">Contradições · velha {quality["stale_evidence"]}%</span></td>
      </tr>
    </table>

    <h2>Síntese</h2>
    <div class="lede">{_paragraphs(summary)}</div>

    <h2>Entidades <span>({len(entities)})</span></h2>
    <table class="data">
      <tr><th>Tipo</th><th>Nome</th><th>Identificadores</th><th>Veredito</th><th>Confiança</th><th>Citações</th></tr>
      {''.join(rows) or _empty(6, "Nenhuma entidade no caso.")}
    </table>

    <h2>Vínculos <span>({len(edges)})</span></h2>
    <table class="data">
      <tr><th>De</th><th>Relação</th><th>Para</th><th>Fonte</th></tr>
      {''.join(links) or _empty(4, "Nenhum vínculo registado.")}
    </table>

    <h2>Evidências <span>({len(evidence)})</span></h2>
    <table class="data">
      <tr><th>#</th><th>Fonte</th><th>Método</th><th>HTTP</th><th>Coletado</th><th>Hash</th><th>URL</th><th>Trecho</th></tr>
      {''.join(ev_rows) or _empty(8, "Nenhuma evidência citada.")}
    </table>

    <h2>Anotações</h2>
    <table class="data"><tr><th>Título</th><th>Texto</th><th>Autor</th></tr>{note_rows}</table>

    <h2>Tarefas</h2>
    <table class="data"><tr><th>Tarefa</th><th>Estado</th><th>Responsável</th></tr>{task_rows}</table>

    <h2>Anexos</h2>
    <table class="data"><tr><th>Arquivo</th><th>Caminho</th></tr>{att_rows}</table>

    <p class="disclaimer">
      Material para jornalismo investigativo. Só fontes públicas e oficiais.
      Cada evidência tem fonte, data, método e hash. Não substitui certidão oficial.
      Não inclui bases restritas (DETRAN, cartório, operadora) nem conteúdo privado de redes sociais.
      Reproduza a conclusão pelas citações [n].
    </p>
    <p class="foot">OSINT4ALL · Confidencialidade conforme classificação do caso · {escape(generated)}</p>
  </article>
  </div>
</body>
</html>
"""


def render_dossier_pdf(session: Session, investigation_id: str) -> bytes:
    html = render_dossier_html(session, investigation_id, for_pdf=True)
    from xhtml2pdf import pisa

    buf = BytesIO()
    pisa.CreatePDF(html, dest=buf)
    return buf.getvalue()
