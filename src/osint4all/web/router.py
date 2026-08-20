"""Rotas HTML do painel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from osint4all.catalog.framework import load_framework_tree
from osint4all.documents.metadata import ingest_local_pdf
from osint4all.config import ALL_CONNECTORS, get_settings
from osint4all.paths import project_root
from osint4all.connectors.registry import connector_health, enabled_connector_names
from osint4all.db.chain import active_chain, alvo_fields, chain_seeds, chain_view, ingest_outcome, reset_chain
from osint4all.db.history import clear_searches, kind_label as history_kind_label, list_searches, record_search, replay_spec
from osint4all.db.models import AuditLog, Edge, Entity, Evidence, ExpansionJob, Investigation, User
from osint4all.db.repository import (
    EDGE_REL_TYPES,
    add_case_note,
    confirm_entity,
    create_manual_edge,
    delete_case_note,
    delete_edge,
    detach_entity,
    enqueue_expand,
    enqueue_qsa_network,
    graph_payload,
    job_counts,
    list_notes,
    note_tree,
    update_edge,
)
from osint4all.graph.expand import process_pending_jobs
from osint4all.consult import MODES, ConsultResult, public_ficha, run_consult
from osint4all.graph.layers import ALVO_GROUPS, confirmed_seeds, qsa_confirms_name, run_alvo_layer
from osint4all.graph.seed import add_seed_entities, attach_plate_owner, create_investigation
from osint4all.tools_suite import MassResult, get_tool, list_tools, run_embedded_tool, run_mass, seeds_from_results, tool_id_for_kind
from osint4all.identifiers import parse_seed, parse_seed_lines
from osint4all.validators import looks_like_plate
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
templates.env.globals["tool_id_for_kind"] = tool_id_for_kind
router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _cases(session: Session) -> list[Investigation]:
    return list(session.scalars(select(Investigation).order_by(desc(Investigation.created_at))).all())


def _with_cases(ctx: dict, request: Request, session: Session) -> dict:
    rows = _cases(session)
    cid = request.session.get("current_case_id")
    ctx["cases"] = rows
    ctx["current_case_id"] = cid
    ctx["current_case"] = next((row for row in rows if row.id == cid), None)
    return ctx


def _history_view(session: Session, user: User) -> list[dict]:
    items: list[dict] = []
    for row in list_searches(session, user):
        stamp = row.created_at.strftime("%d/%m %H:%M") if row.created_at else ""
        spec = replay_spec(row.mode, row.kind)
        items.append(
            {
                "id": row.id,
                "query": row.query,
                "mode": spec["mode"],
                "tool": spec["tool"],
                "action": spec["action"],
                "kind": row.kind,
                "kind_label": history_kind_label(row.kind or row.mode),
                "title": row.title or row.query,
                "summary": row.summary,
                "ok": row.ok,
                "when": stamp,
            }
        )
    return items


def _with_history(ctx: dict, session: Session, user: User) -> dict:
    ctx["history"] = _history_view(session, user)
    return ctx


def _with_chain(ctx: dict, session: Session, user: User, *, current_query: str = "") -> dict:
    ctx["chain"] = chain_view(session, user, current_query=current_query)
    return ctx


def _save_search(session: Session, user: User, query: str, mode: str, outcome: object) -> None:
    record_search(
        session,
        user,
        query=query,
        mode=mode,
        kind=str(getattr(outcome, "kind", "") or ""),
        title=str(getattr(outcome, "title", "") or query),
        summary=str(getattr(outcome, "summary", "") or getattr(outcome, "error", "") or ""),
        ok=bool(getattr(outcome, "ok", True)),
    )


def _assign_seeds(
    session: Session,
    inv: Investigation,
    parts: list[ConsultResult],
    *,
    owner: str = "",
) -> int:
    seeds = seeds_from_results(parts)
    if not seeds:
        return 0
    add_seed_entities(session, inv, seeds, max_attempts=get_settings().job_max_attempts)
    plate = next((s for s in seeds if s.kind == "PLATE"), None)
    if plate and owner.strip():
        attach_plate_owner(
            session,
            inv,
            plate=plate.value,
            owner_name=owner.strip(),
            max_attempts=get_settings().job_max_attempts,
        )
    if get_settings().expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=get_settings().expand_sync_limit)
    return len(seeds)


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
def consult_home(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "consultar",
            "modes": MODES,
            "mode": request.query_params.get("modo") or "auto",
            "q": request.query_params.get("q") or "",
        }
    )
    _with_cases(ctx, request, session)
    _with_history(ctx, session, user)
    _with_chain(ctx, session, user)
    return templates.TemplateResponse(request, "app/consult.html", ctx)


@router.post("/app/consultar", response_class=HTMLResponse)
def consult_run(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    q: str = Form(""),
    modo: str = Form("auto"),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    ctx = template_context(request, user)
    ctx.update({"q": q, "modo": modo, "nav": "consultar", "modes": MODES, "mode": modo})
    _with_cases(ctx, request, session)
    if (modo or "").lower() == "massa":
        try:
            mass = run_mass(q)
        except Exception as exc:  # noqa: BLE001
            mass = MassResult(query=q, kind="massa", title=q, summary="", ok=False, error=str(exc) or "Busca em massa falhou.")
        write_audit(session, "consult.mass", username=user.username, details={"ok": mass.ok, "parts": len(mass.parts)})
        _save_search(session, user, q, "massa", mass)
        ingest_outcome(session, user, mass)
        ctx["mass"] = mass
        _with_history(ctx, session, user)
        _with_chain(ctx, session, user, current_query=q)
        template = "app/consult_mass.html" if request.headers.get("HX-Request") else "app/consult.html"
        return templates.TemplateResponse(request, template, ctx)
    result = run_consult(q, mode=modo)
    write_audit(session, "consult.run", username=user.username, details={"kind": result.kind, "ok": result.ok})
    _save_search(session, user, q, modo, result)
    ingest_outcome(session, user, result)
    ctx["result"] = result
    _with_history(ctx, session, user)
    _with_chain(ctx, session, user, current_query=q)
    template = "app/consult_result.html" if request.headers.get("HX-Request") else "app/consult.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/app/ficha.json")
def ficha_lookup(
    q: str = "",
    modo: str = "auto",
    user: User = Depends(current_user),
) -> JSONResponse:
    card = public_ficha(q, mode=modo)
    return JSONResponse(card)


@router.post("/app/historico/limpar")
def history_clear(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> Response:
    require_csrf(request, csrf_token)
    clear_searches(session, user)
    if request.headers.get("HX-Request"):
        ctx = template_context(request, user)
        ctx["history"] = []
        return templates.TemplateResponse(request, "app/search_history.html", ctx)
    return RedirectResponse("/app", status_code=303)


@router.post("/app/cadeia/nova")
def chain_reset(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> Response:
    require_csrf(request, csrf_token)
    reset_chain(session, user)
    if request.headers.get("HX-Request"):
        ctx = template_context(request, user)
        ctx["chain"] = None
        return templates.TemplateResponse(request, "app/consult_chain.html", ctx)
    return RedirectResponse("/app", status_code=303)


@router.post("/app/cadeia/grafo")
def chain_to_graph(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    chain = active_chain(session, user)
    seeds = chain_seeds(session, chain) if chain else []
    if not chain or not seeds:
        request.session["flash"] = {"level": "error", "message": "Não há cadeia com identificadores para guardar."}
        return RedirectResponse("/app", status_code=303)
    inv = create_investigation(
        session,
        title=chain.title or "Cadeia de consultas",
        hypothesis="Gerada a partir da cadeia de buscas relacionadas.",
        seeds=seeds,
        connectors=list(enabled_connector_names()),
        max_depth=get_settings().default_max_depth,
        monitor=False,
        created_by=user.username,
        max_attempts=get_settings().job_max_attempts,
    )
    write_audit(session, "investigation.from_chain", username=user.username, investigation_id=inv.id, details={"steps": len(seeds)})
    session.commit()
    request.session["current_case_id"] = inv.id
    request.session["flash"] = {"level": "ok", "message": f"Caso criado a partir da cadeia · {len(seeds)} identificador(es)."}
    if get_settings().expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=get_settings().expand_sync_limit)
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


def _alvo_page(request: Request, user: User, session: Session, *, fields: dict | None = None, layer=None) -> HTMLResponse:
    ctx = template_context(request, user)
    ctx.update({"nav": "alvo", "groups": ALVO_GROUPS, "fields": fields if fields is not None else alvo_fields(session, user)})
    if layer is not None:
        ctx["layer"] = layer
    _with_cases(ctx, request, session)
    return templates.TemplateResponse(request, "app/alvo.html", ctx)


def _apply_alvo_layer(request: Request, session: Session, user: User, kind: str, value: str, *, live: bool = True):
    fields = alvo_fields(session, user)
    layer = run_alvo_layer(fields, kind=kind, value=value, live=live)
    if layer.consult and layer.consult.ok:
        ingest_outcome(session, user, layer.consult)
    persisted = alvo_fields(session, user)
    for key, stored in persisted.items():
        if stored and not layer.fields.get(key):
            layer.fields[key] = stored
    request.session["alvo_qsa_match"] = bool(layer.qsa_match)
    return layer


@router.get("/app/alvo", response_class=HTMLResponse)
def alvo_home(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    return _alvo_page(request, user, session)


@router.post("/app/alvo", response_class=HTMLResponse)
def alvo_run(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    kind: str = Form(""),
    value: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    layer = _apply_alvo_layer(request, session, user, kind, value)
    write_audit(session, "alvo.layer", username=user.username, details={"kind": kind, "ok": layer.ok, "qsa": layer.qsa_match})
    return _alvo_page(request, user, session, fields=layer.fields, layer=layer)


@router.post("/app/alvo/confirmar", response_class=HTMLResponse)
def alvo_confirm(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    kind: str = Form(""),
    value: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    layer = _apply_alvo_layer(request, session, user, kind, value, live=True)
    write_audit(session, "alvo.confirm", username=user.username, details={"kind": kind, "ok": layer.ok, "qsa": layer.qsa_match})
    request.session["flash"] = {"level": "ok", "message": f"Campo {kind} confirmado no alvo. Nova camada rodou."}
    return _alvo_page(request, user, session, fields=layer.fields, layer=layer)


@router.post("/app/alvo/grafo")
def alvo_to_graph(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    investigation_id: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    fields = alvo_fields(session, user)
    qsa_match = bool(request.session.get("alvo_qsa_match"))
    if fields.get("NAME") and fields.get("CNPJ") and not qsa_match:
        qsa_match = qsa_confirms_name(fields["CNPJ"], fields["NAME"])
        request.session["alvo_qsa_match"] = qsa_match
    seeds = confirmed_seeds(fields, qsa_match=qsa_match)
    if not seeds:
        request.session["flash"] = {
            "level": "error",
            "message": "Nada confirmado ainda. Nome sozinho não abre grafo — acrescente CPF, CNPJ, e-mail, telefone, placa ou @user.",
        }
        return RedirectResponse("/app/alvo", status_code=303)
    target_id = investigation_id or request.session.get("current_case_id") or ""
    inv = session.get(Investigation, target_id) if target_id else None
    if inv:
        add_seed_entities(session, inv, seeds, max_attempts=get_settings().job_max_attempts)
        write_audit(session, "investigation.from_alvo", username=user.username, investigation_id=inv.id, details={"added": len(seeds)})
    else:
        name = fields.get("NAME") or seeds[0].display_name
        inv = create_investigation(
            session,
            title=f"Alvo · {name}",
            hypothesis="Dossiê do alvo em camadas. Vínculos por âncora forte ou QSA.",
            seeds=seeds,
            connectors=list(enabled_connector_names()),
            max_depth=4,
            monitor=False,
            created_by=user.username,
            max_attempts=get_settings().job_max_attempts,
        )
        write_audit(session, "investigation.from_alvo", username=user.username, investigation_id=inv.id, details={"seeds": len(seeds)})
    session.commit()
    request.session["current_case_id"] = inv.id
    if get_settings().expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=get_settings().expand_sync_limit)
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.post("/app/consultar/grafo")
def consult_to_graph(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    kind: str = Form(""),
    value: str = Form(""),
    owner: str = Form(""),
    values: list[str] = Form(default=[]),
    kinds: list[str] = Form(default=[]),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    seeds = []
    seen: set[str] = set()
    candidates = [(kind, value), *zip(kinds, values, strict=False)]
    for item_kind, item_value in candidates:
        if not item_value:
            continue
        seed = parse_seed(item_value, forced_kind=item_kind or None)
        if seed and seed.canonical_key not in seen:
            seen.add(seed.canonical_key)
            seeds.append(seed)
    if not seeds:
        request.session["flash"] = {"level": "error", "message": "Não deu para abrir o grafo com esse valor."}
        return RedirectResponse("/app", status_code=303)
    seed = seeds[0]
    inv = create_investigation(
        session,
        title=f"Consulta · {seed.display_name}",
        hypothesis="Gerada a partir de uma consulta rápida.",
        seeds=seeds,
        connectors=list(enabled_connector_names()),
        max_depth=get_settings().default_max_depth,
        monitor=False,
        created_by=user.username,
        max_attempts=get_settings().job_max_attempts,
    )
    plate = next((item for item in seeds if item.kind == "PLATE"), None)
    if plate:
        attach_plate_owner(
            session,
            inv,
            plate=plate.value,
            owner_name=owner.strip(),
            max_attempts=get_settings().job_max_attempts,
        )
    write_audit(session, "investigation.from_consult", username=user.username, investigation_id=inv.id, details={"kind": seed.kind, "seeds": len(seeds)})
    session.commit()
    request.session["current_case_id"] = inv.id
    if get_settings().expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=get_settings().expand_sync_limit)
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.post("/app/consultar/atribuir")
def consult_assign(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    kind: str = Form(""),
    value: str = Form(""),
    owner: str = Form(""),
    investigation_id: str = Form(""),
    values: list[str] = Form(default=[]),
    kinds: list[str] = Form(default=[]),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    target_id = investigation_id or request.session.get("current_case_id") or ""
    inv = session.get(Investigation, target_id) if target_id else None
    if not inv:
        request.session["flash"] = {"level": "error", "message": "Escolha um caso corrente ou crie um em Montar caso."}
        return RedirectResponse("/app/casos", status_code=303)
    parts: list[ConsultResult] = []
    if value:
        parts.append(ConsultResult(kind=kind, query=value, title=value, summary="", ok=True))
    for item_kind, item_value in zip(kinds, values, strict=False):
        if item_value:
            parts.append(ConsultResult(kind=item_kind, query=item_value, title=item_value, summary="", ok=True))
    added = _assign_seeds(session, inv, parts, owner=owner)
    request.session["current_case_id"] = inv.id
    write_audit(session, "investigation.assign_consult", username=user.username, investigation_id=inv.id, details={"added": added})
    session.commit()
    request.session["flash"] = {"level": "ok", "message": f"{added} identificador(es) adicionados a {inv.title}."}
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.get("/app/casos", response_class=HTMLResponse)
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
    seed_plate: str = Form(""),
    seed_plate_owner: str = Form(""),
    seed_plate_cpf: str = Form(""),
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
        parse_seed(seed_plate, forced_kind="PLATE") if looks_like_plate(seed_plate) else None,
        parse_seed(seed_plate_cpf, forced_kind="CPF"),
        parse_seed(seed_plate_owner, forced_kind="NAME"),
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
    if looks_like_plate(seed_plate):
        attach_plate_owner(
            session,
            inv,
            plate=seed_plate,
            owner_name=seed_plate_owner,
            owner_cpf=seed_plate_cpf,
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
    request.session["current_case_id"] = inv.id
    notes = list_notes(session, inv.id)
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
            "board_note_flat": notes,
            "board_notes": note_tree(notes),
            "board_entities": session.scalars(
                select(Entity).where(Entity.investigation_id == inv.id).order_by(Entity.display_name)
            ).all(),
            "rel_types": EDGE_REL_TYPES,
        }
    )
    return templates.TemplateResponse(request, "app/graph.html", ctx)


@router.post("/app/casos/{investigation_id}/usar")
def use_case(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        request.session["flash"] = {"level": "error", "message": "Investigação não encontrada."}
        return RedirectResponse("/app/casos", status_code=303)
    request.session["current_case_id"] = inv.id
    request.session["flash"] = {"level": "ok", "message": f"Caso corrente: {inv.title}."}
    nxt = request.query_params.get("next") or "/app"
    return RedirectResponse(nxt, status_code=303)


@router.post("/app/casos/{investigation_id}/editar")
def edit_case(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    title: str = Form(""),
    hypothesis: str = Form(""),
    max_depth: int = Form(2),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return RedirectResponse("/app/casos", status_code=303)
    if title.strip():
        inv.title = title.strip()[:255]
    inv.hypothesis = hypothesis.strip() or None
    inv.max_depth = max(0, min(max_depth, 4))
    write_audit(session, "investigation.edit", username=user.username, investigation_id=inv.id)
    session.commit()
    request.session["flash"] = {"level": "ok", "message": "Caso atualizado."}
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


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
    payload = graph_payload(session, investigation_id)
    counts = job_counts(session, investigation_id)
    counts["entities"] = payload.get("entity_count") or 0
    counts["edges"] = payload.get("edge_count") or 0
    return JSONResponse(counts)


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
    partner_companies: list[tuple[Edge, Entity]] = []
    company_partners: list[tuple[Edge, Entity]] = []
    for edge in edges:
        if edge.rel_type not in {"SOCIO", "ADMIN"}:
            continue
        other_id = edge.to_entity_id if edge.from_entity_id == entity.id else edge.from_entity_id
        other = neighbors.get(other_id)
        if not other:
            continue
        if entity.entity_type == "PERSON" and other.entity_type == "ORG":
            partner_companies.append((edge, other))
        if entity.entity_type == "ORG" and other.entity_type in {"PERSON", "ORG"}:
            company_partners.append((edge, other))
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
            "partner_companies": partner_companies,
            "company_partners": company_partners,
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


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/editar")
def edit_entity(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    display_name: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    entity = session.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not entity:
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    if display_name.strip():
        entity.display_name = display_name.strip()[:512]
    attrs = dict(entity.attrs or {})
    if note.strip():
        attrs["nota"] = note.strip()[:2000]
    elif "nota" in attrs and not note.strip():
        attrs.pop("nota", None)
    entity.attrs = attrs
    write_audit(session, "entity.edit", username=user.username, investigation_id=investigation_id, details={"entity_id": entity.id})
    session.commit()
    request.session["flash"] = {"level": "ok", "message": "Ficha atualizada."}
    return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/confirmar")
def confirm_node(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    entity = session.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not entity:
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    confirm_entity(session, entity, reason="Confirmado na ficha do alvo.")
    inv = session.get(Investigation, investigation_id)
    if inv:
        enqueue_expand(session, investigation=inv, entity=entity, depth=entity.depth, max_attempts=get_settings().job_max_attempts)
    write_audit(session, "entity.confirm", username=user.username, investigation_id=investigation_id, details={"entity_id": entity_id})
    session.commit()
    if get_settings().expand_sync:
        process_pending_jobs(investigation_id=investigation_id, limit=get_settings().expand_sync_limit)
    request.session["flash"] = {"level": "ok", "message": "Nó confirmado. A próxima camada pode expandir daqui."}
    return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/desligar")
def detach_node(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    ok = detach_entity(session, investigation_id, entity_id)
    if ok:
        write_audit(session, "entity.detach", username=user.username, investigation_id=investigation_id, details={"entity_id": entity_id})
        session.commit()
        request.session["flash"] = {"level": "ok", "message": "Nó desligado e vínculos removidos."}
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/explodir")
def explode_qsa(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return RedirectResponse("/app/casos", status_code=303)
    queued = enqueue_qsa_network(session, inv, max_attempts=get_settings().job_max_attempts)
    write_audit(
        session,
        "investigation.explode_qsa",
        username=user.username,
        investigation_id=inv.id,
        details={"queued": queued, "max_depth": inv.max_depth},
    )
    session.commit()
    processed = 0
    if get_settings().expand_sync:
        for _ in range(6):
            n = process_pending_jobs(investigation_id=inv.id, limit=10)
            if not n:
                break
            processed += n
    request.session["flash"] = {
        "level": "ok",
        "message": (
            f"QSA explodido até o nível {inv.max_depth}: {queued} âncora(s) na fila, {processed} lote(s) rodado(s). "
            "Sócios só com nome entram como candidatos; CNPJ/CPF seguem expandindo."
        ),
    }
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


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


@router.post("/app/casos/{investigation_id}/notas")
def add_note(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    title: str = Form(""),
    body: str = Form(""),
    entity_id: str = Form(""),
    parent_id: str = Form(""),
    on_graph: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return RedirectResponse("/app/casos", status_code=303)
    add_case_note(
        session,
        inv,
        title=title,
        body=body,
        entity_id=entity_id or None,
        parent_id=parent_id or None,
        created_by=user.username,
        on_graph=bool(on_graph),
    )
    write_audit(session, "note.add", username=user.username, investigation_id=inv.id, details={"on_graph": bool(on_graph)})
    session.commit()
    request.session["flash"] = {"level": "ok", "message": "Anotação gravada no caso."}
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.post("/app/casos/{investigation_id}/notas/{note_id}/apagar")
def remove_note(
    investigation_id: str,
    note_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    if delete_case_note(session, investigation_id, note_id):
        write_audit(session, "note.delete", username=user.username, investigation_id=investigation_id, details={"note_id": note_id})
        session.commit()
        request.session["flash"] = {"level": "ok", "message": "Anotação removida."}
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/ligacoes")
def add_link(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    from_id: str = Form(""),
    to_id: str = Form(""),
    rel_type: str = Form("RELACIONADO"),
    note: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return RedirectResponse("/app/casos", status_code=303)
    edge = create_manual_edge(session, inv, from_id=from_id, to_id=to_id, rel_type=rel_type, note=note)
    write_audit(session, "edge.create", username=user.username, investigation_id=inv.id, details={"rel": rel_type})
    session.commit()
    request.session["flash"] = {
        "level": "ok" if edge else "error",
        "message": "Ligação gravada no grafo." if edge else "Escolha dois nós diferentes.",
    }
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.get("/app/casos/{investigation_id}/ligacoes/{edge_id}", response_class=HTMLResponse)
def edge_page(
    investigation_id: str,
    edge_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    inv = session.get(Investigation, investigation_id)
    edge = session.scalar(select(Edge).where(Edge.id == edge_id, Edge.investigation_id == investigation_id))
    if not inv or not edge:
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    src = session.get(Entity, edge.from_entity_id)
    dst = session.get(Entity, edge.to_entity_id)
    ctx = template_context(request, user)
    ctx.update({"nav": "casos", "inv": inv, "edge": edge, "src": src, "dst": dst, "rel_types": EDGE_REL_TYPES})
    return templates.TemplateResponse(request, "app/edge.html", ctx)


@router.post("/app/casos/{investigation_id}/ligacoes/{edge_id}/editar")
def edit_link(
    investigation_id: str,
    edge_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    rel_type: str = Form("RELACIONADO"),
    note: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    edge = update_edge(session, investigation_id, edge_id, rel_type=rel_type, note=note)
    if edge:
        write_audit(session, "edge.edit", username=user.username, investigation_id=investigation_id, details={"rel": rel_type})
        session.commit()
        request.session["flash"] = {"level": "ok", "message": "Ligação atualizada."}
    return RedirectResponse(f"/app/casos/{investigation_id}/ligacoes/{edge_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/ligacoes/{edge_id}/apagar")
def remove_link(
    investigation_id: str,
    edge_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    if delete_edge(session, investigation_id, edge_id):
        write_audit(session, "edge.delete", username=user.username, investigation_id=investigation_id, details={"edge_id": edge_id})
        session.commit()
        request.session["flash"] = {"level": "ok", "message": "Ligação removida. Os nós continuam no caso."}
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/placa")
def add_plate(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    seed_plate: str = Form(""),
    seed_plate_owner: str = Form(""),
    seed_plate_cpf: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        request.session["flash"] = {"level": "error", "message": "Investigação não encontrada."}
        return RedirectResponse("/app", status_code=303)
    if not looks_like_plate(seed_plate):
        request.session["flash"] = {"level": "error", "message": "Informe uma placa válida (ABC1D23 ou ABC-1234)."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    attach_plate_owner(
        session,
        inv,
        plate=seed_plate,
        owner_name=seed_plate_owner,
        owner_cpf=seed_plate_cpf,
        max_attempts=get_settings().job_max_attempts,
    )
    write_audit(
        session,
        "investigation.add_plate",
        username=user.username,
        investigation_id=inv.id,
        details={"placa": seed_plate.strip()},
    )
    session.commit()
    settings = get_settings()
    if settings.expand_sync:
        process_pending_jobs(investigation_id=inv.id, limit=settings.expand_sync_limit, settings=settings)
    request.session["flash"] = {"level": "ok", "message": "Veículo adicionado ao grafo."}
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
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv:
        write_audit(session, "investigation.purge", username=user.username, investigation_id=inv.id)
        session.delete(inv)
        session.commit()
        upload = project_root() / "data" / "uploads" / investigation_id
        if upload.exists():
            import shutil

            shutil.rmtree(upload, ignore_errors=True)
        if request.session.get("current_case_id") == investigation_id:
            request.session.pop("current_case_id", None)
        request.session["flash"] = {"level": "ok", "message": "Caso apagado. Nós, vínculos, notas e uploads foram removidos."}
    return RedirectResponse("/app/casos", status_code=303)


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
    session: Session = Depends(db_session),
) -> HTMLResponse:
    needle = request.query_params.get("busca") or ""
    tool_id = request.query_params.get("tool") or tool_id_for_kind(request.query_params.get("kind") or "")
    selected = get_tool(tool_id) or get_tool("massa")
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "ferramentas",
            "tools": list_tools(needle),
            "selected": selected,
            "seed": request.query_params.get("q") or "",
            "kind": request.query_params.get("kind") or "",
            "busca": needle,
        }
    )
    _with_cases(ctx, request, session)
    _with_history(ctx, session, user)
    _with_chain(ctx, session, user)
    return templates.TemplateResponse(request, "app/tools.html", ctx)


@router.post("/app/ferramentas/executar", response_class=HTMLResponse)
def tools_run(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    tool: str = Form("massa"),
    q: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        outcome = run_embedded_tool(tool, q)
    except Exception as exc:  # noqa: BLE001
        outcome = MassResult(query=q, kind="massa", title=q, summary="", ok=False, error=str(exc) or "Ferramenta falhou.") if (tool or "").lower() == "massa" else ConsultResult(kind=tool, query=q, title=q, summary="", ok=False, error=str(exc) or "Ferramenta falhou.")
    write_audit(session, "tool.run", username=user.username, details={"tool": tool, "ok": getattr(outcome, "ok", True)})
    _save_search(session, user, q, tool, outcome)
    ingest_outcome(session, user, outcome)
    ctx = template_context(request, user)
    _with_cases(ctx, request, session)
    _with_history(ctx, session, user)
    _with_chain(ctx, session, user, current_query=q)
    ctx.update({"tool_id": tool, "q": q})
    if isinstance(outcome, MassResult):
        ctx["mass"] = outcome
        template = "app/consult_mass.html"
    else:
        ctx["result"] = outcome
        template = "app/consult_result.html"
    return templates.TemplateResponse(request, template, ctx)


@router.get("/app/ferramentas/arvore.json")
def tools_tree_json(
    user: User = Depends(current_user),
    refresh: bool = False,
) -> JSONResponse:
    if user.role != "admin":
        refresh = False
    tree = load_framework_tree(refresh=refresh)
    return JSONResponse(tree)
