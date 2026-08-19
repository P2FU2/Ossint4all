"""Rotas HTML do painel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from osint4all.catalog.framework import load_framework_tree, matching_branches, tree_stats
from osint4all.documents.metadata import ingest_local_pdf
from osint4all.config import ALL_CONNECTORS, get_settings
from osint4all.paths import project_root
from osint4all.connectors.registry import connector_health, enabled_connector_names
from osint4all.db.models import AuditLog, Edge, Entity, Evidence, ExpansionJob, Investigation, User
from osint4all.db.repository import enqueue_expand, graph_payload, job_counts
from osint4all.graph.expand import process_pending_jobs
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed, parse_seed_lines
from osint4all.report.dossier import render_dossier_html, render_dossier_pdf
from osint4all.security import mask_identifier
from osint4all.web.auth import (
    SESSION_USER_KEY,
    authenticate_user,
    check_login_rate_limit,
    clear_login_failures,
    ensure_csrf,
    record_login_failure,
    write_audit,
)
from osint4all.web.deps import current_user, db_session, require_admin, require_csrf, template_context

templates = Jinja2Templates(directory=str(project_root() / "templates"))
router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    ctx = template_context(request)
    return templates.TemplateResponse(request, "app/login.html", ctx)


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    session: Session = Depends(db_session),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    ip = _client_ip(request)
    if not check_login_rate_limit(ip):
        request.session["flash"] = {"level": "error", "message": "Muitas tentativas. Aguarde."}
        return RedirectResponse("/login", status_code=303)
    user = authenticate_user(session, username, password)
    if not user:
        record_login_failure(ip)
        write_audit(session, "auth.login_failed", username=username, details={"ip": ip})
        request.session["flash"] = {"level": "error", "message": "Usuário ou senha inválidos."}
        return RedirectResponse("/login", status_code=303)
    clear_login_failures(ip)
    request.session[SESSION_USER_KEY] = user.id
    ensure_csrf(request.session)
    write_audit(session, "auth.login", username=user.username)
    return RedirectResponse("/app", status_code=303)


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(""),
    session: Session = Depends(db_session),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    uid = request.session.get(SESSION_USER_KEY)
    user = session.get(User, str(uid)) if uid else None
    write_audit(session, "auth.logout", username=user.username if user else None)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse("/app", status_code=303)


@router.get("/app/dashboard")
@router.get("/app/status")
@router.get("/app/processes")
@router.get("/app/events")
@router.get("/app/criteria")
@router.get("/app/acompanhamento")
@router.get("/app/system")
def legacy_script_jus_pages() -> RedirectResponse:
    return RedirectResponse("/app", status_code=303)


@router.get("/app", response_class=HTMLResponse)
def investigations(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    rows = session.scalars(select(Investigation).order_by(desc(Investigation.created_at))).all()
    counts = {
        inv.id: {
            "entities": session.scalar(
                select(func.count()).select_from(Entity).where(Entity.investigation_id == inv.id)
            )
            or 0,
            "edges": session.scalar(
                select(func.count()).select_from(Edge).where(Edge.investigation_id == inv.id)
            )
            or 0,
            "jobs": job_counts(session, inv.id),
        }
        for inv in rows
    }
    ctx = template_context(request, user)
    ctx.update({"nav": "casos", "investigations": rows, "counts": counts})
    return templates.TemplateResponse(request, "app/investigations.html", ctx)


@router.get("/app/nova", response_class=HTMLResponse)
def new_investigation(
    request: Request,
    user: User = Depends(current_user),
) -> HTMLResponse:
    settings = get_settings()
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "nova",
            "connectors": ALL_CONNECTORS,
            "enabled": enabled_connector_names(settings),
            "default_depth": settings.default_max_depth,
        }
    )
    return templates.TemplateResponse(request, "app/new.html", ctx)


@router.post("/app/nova")
def create_case(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    title: str = Form(""),
    hypothesis: str = Form(""),
    seeds: str = Form(""),
    seed_cpf: str = Form(""),
    seed_cnpj: str = Form(""),
    seed_name: str = Form(""),
    seed_email: str = Form(""),
    seed_phone: str = Form(""),
    seed_username: str = Form(""),
    max_depth: int = Form(2),
    monitor: str = Form(""),
    connectors: list[str] = Form(default=[]),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    parsed = parse_seed_lines(seeds)
    extras = [
        parse_seed(seed_cpf, forced_kind="CPF"),
        parse_seed(seed_cnpj, forced_kind="CNPJ"),
        parse_seed(seed_name, forced_kind="NAME"),
        parse_seed(seed_email, forced_kind="EMAIL"),
        parse_seed(seed_phone, forced_kind="PHONE"),
        parse_seed(seed_username, forced_kind="USERNAME"),
    ]
    seen = {s.canonical_key for s in parsed}
    for extra in extras:
        if extra and extra.canonical_key not in seen:
            parsed.append(extra)
            seen.add(extra.canonical_key)
    if not parsed:
        request.session["flash"] = {"level": "error", "message": "Informe ao menos uma semente válida."}
        return RedirectResponse("/app/nova", status_code=303)
    chosen = [c for c in connectors if c in ALL_CONNECTORS] or list(enabled_connector_names())
    inv = create_investigation(
        session,
        title=title,
        hypothesis=hypothesis,
        seeds=parsed,
        connectors=chosen,
        max_depth=max_depth,
        monitor=monitor == "on",
        created_by=user.username,
        max_attempts=get_settings().job_max_attempts,
    )
    write_audit(
        session,
        "investigation.create",
        username=user.username,
        investigation_id=inv.id,
        details={"seeds": len(parsed), "connectors": chosen},
    )
    session.commit()
    settings = get_settings()
    if settings.expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=settings.expand_sync_limit, settings=settings)
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.get("/app/casos/{investigation_id}", response_class=HTMLResponse)
def graph_page(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    inv = session.get(Investigation, investigation_id)
    if not inv:
        request.session["flash"] = {"level": "error", "message": "Investigação não encontrada."}
        return RedirectResponse("/app", status_code=303)
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "casos",
            "inv": inv,
            "jobs": job_counts(session, inv.id),
            "entity_count": session.scalar(
                select(func.count()).select_from(Entity).where(Entity.investigation_id == inv.id)
            )
            or 0,
            "edge_count": session.scalar(
                select(func.count()).select_from(Edge).where(Edge.investigation_id == inv.id)
            )
            or 0,
        }
    )
    return templates.TemplateResponse(request, "app/graph.html", ctx)


@router.get("/app/casos/{investigation_id}/grafo.json")
def graph_json(
    investigation_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> JSONResponse:
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(graph_payload(session, investigation_id))


@router.get("/app/casos/{investigation_id}/status")
def job_status(
    investigation_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> JSONResponse:
    return JSONResponse(job_counts(session, investigation_id))


@router.get("/app/casos/{investigation_id}/entidades/{entity_id}", response_class=HTMLResponse)
def entity_page(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    entity = session.scalar(
        select(Entity)
        .options(selectinload(Entity.identifiers), selectinload(Entity.evidence))
        .where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not entity:
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    edges = session.scalars(
        select(Edge).where(
            Edge.investigation_id == investigation_id,
            (Edge.from_entity_id == entity_id) | (Edge.to_entity_id == entity_id),
        )
    ).all()
    neighbor_ids = {e.from_entity_id for e in edges} | {e.to_entity_id for e in edges}
    neighbors = {
        n.id: n
        for n in session.scalars(select(Entity).where(Entity.id.in_(neighbor_ids or {"_"}))).all()
    }
    evidence = session.scalars(
        select(Evidence)
        .where(Evidence.entity_id == entity_id)
        .order_by(desc(Evidence.collected_at))
    ).all()
    seed_ident = entity.identifiers[0] if entity.identifiers else None
    seed_kind = seed_ident.kind if seed_ident else (
        "NAME" if entity.entity_type == "PERSON" else entity.entity_type
    )
    seed_q = seed_ident.value if seed_ident else entity.display_name
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "casos",
            "inv": session.get(Investigation, investigation_id),
            "entity": entity,
            "edges": edges,
            "neighbors": neighbors,
            "evidence": evidence,
            "mask_identifier": mask_identifier,
            "seed_kind": seed_kind,
            "seed_q": seed_q,
        }
    )
    return templates.TemplateResponse(request, "app/entity.html", ctx)


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/expandir")
def expand_here(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    entity = session.get(Entity, entity_id)
    if not inv or not entity or entity.investigation_id != inv.id:
        return RedirectResponse("/app", status_code=303)
    enqueue_expand(
        session,
        investigation=inv,
        entity=entity,
        depth=entity.depth,
        max_attempts=get_settings().job_max_attempts,
    )
    # força reprocessamento mesmo se já DONE: cria job novo se necessário
    existing_done = session.scalar(
        select(ExpansionJob).where(
            ExpansionJob.entity_id == entity.id,
            ExpansionJob.status == "DONE",
        )
    )
    if existing_done:
        session.add(
            ExpansionJob(
                investigation_id=inv.id,
                entity_id=entity.id,
                depth=entity.depth,
                max_attempts=get_settings().job_max_attempts,
            )
        )
    write_audit(
        session,
        "entity.expand",
        username=user.username,
        investigation_id=inv.id,
        details={"entity_id": entity.id},
    )
    session.commit()
    if get_settings().expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=get_settings().expand_sync_limit)
    return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/processar")
def process_now(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    process_pending_jobs(investigation_id=investigation_id, limit=get_settings().expand_sync_limit)
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


_MAX_PDF_BYTES = 8 * 1024 * 1024


@router.post("/app/casos/{investigation_id}/documento")
async def attach_pdf(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    arquivo: UploadFile = File(...),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        request.session["flash"] = {"level": "error", "message": "Investigação não encontrada."}
        return RedirectResponse("/app", status_code=303)
    name = arquivo.filename or "documento.pdf"
    if not name.lower().endswith(".pdf"):
        request.session["flash"] = {"level": "error", "message": "Envie um PDF público (máx. 8 MB)."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    data = await arquivo.read(_MAX_PDF_BYTES + 1)
    if len(data) > _MAX_PDF_BYTES:
        request.session["flash"] = {"level": "error", "message": "PDF acima de 8 MB."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    if not data.startswith(b"%PDF"):
        request.session["flash"] = {"level": "error", "message": "Arquivo não parece um PDF."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    entity = ingest_local_pdf(session, inv, filename=name, data=data)
    write_audit(
        session,
        "document.attach",
        username=user.username,
        investigation_id=inv.id,
        details={"entity_id": entity.id, "filename": name},
    )
    request.session["flash"] = {"level": "ok", "message": f"Metadados extraídos de {name}."}
    return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity.id}", status_code=303)


@router.get("/app/casos/{investigation_id}/relatorio", response_class=HTMLResponse)
def dossier_html(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    html = render_dossier_html(session, investigation_id)
    return HTMLResponse(html)


@router.get("/app/casos/{investigation_id}/relatorio.pdf")
def dossier_pdf(
    investigation_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> Response:
    pdf = render_dossier_pdf(session, investigation_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="osint4all-{investigation_id[:8]}.pdf"'},
    )


@router.post("/app/casos/{investigation_id}/monitorar")
def toggle_monitor(
    investigation_id: str,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv:
        inv.monitor = not inv.monitor
        write_audit(
            session,
            "investigation.monitor",
            username=user.username,
            investigation_id=inv.id,
            details={"monitor": inv.monitor},
        )
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/apagar")
def purge_case(
    investigation_id: str,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv:
        write_audit(session, "investigation.purge", username=user.username, investigation_id=inv.id)
        session.delete(inv)
    return RedirectResponse("/app", status_code=303)


@router.get("/app/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    audits = session.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(40)).all()
    jobs = session.scalars(select(ExpansionJob).order_by(desc(ExpansionJob.created_at)).limit(30)).all()
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "admin",
            "health": connector_health(),
            "audits": audits,
            "jobs": jobs,
        }
    )
    return templates.TemplateResponse(request, "app/admin.html", ctx)


@router.get("/app/ferramentas", response_class=HTMLResponse)
def tools_map(
    request: Request,
    user: User = Depends(current_user),
) -> HTMLResponse:
    tree = load_framework_tree()
    stats = tree_stats(tree)
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "ferramentas",
            "stats": stats,
            "source_page": tree.get("source_page") or "https://osintframework.com/",
            "seed": request.query_params.get("q") or "",
            "kind": request.query_params.get("kind") or "",
            "highlights": sorted(matching_branches(request.query_params.get("kind"))),
        }
    )
    return templates.TemplateResponse(request, "app/tools.html", ctx)


@router.get("/app/ferramentas/arvore.json")
def tools_tree_json(
    user: User = Depends(current_user),
    refresh: bool = False,
) -> JSONResponse:
    if user.role != "admin":
        refresh = False
    tree = load_framework_tree(refresh=refresh)
    return JSONResponse(tree)
