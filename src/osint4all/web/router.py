"""Rotas HTML do painel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session, load_only, selectinload

from osint4all.catalog.framework import load_framework_tree
from osint4all.documents.metadata import ingest_local_file
from osint4all.config import ALL_CONNECTORS, get_settings
from osint4all.paths import project_root
from osint4all.catalog.opensource import oss_cards
from osint4all.catalog.sources import SOURCE_CATALOG, source_cards
from osint4all.connectors.registry import connector_health, enabled_connector_names
from osint4all.db.chain import (
    active_chain,
    alvo_fields,
    chain_seeds,
    chain_view,
    ingest_outcome,
    reset_alvo_draft,
    reset_chain,
    save_alvo_fields,
)
from osint4all.db.history import clear_searches, kind_label as history_kind_label, list_searches, record_search, replay_spec
from osint4all.db.models import AuditLog, Edge, Entity, Evidence, ExpansionJob, Investigation, User
from osint4all.db.repository import (
    EDGE_REL_TYPES,
    add_case_note,
    case_identifiers,
    case_known_keys,
    case_target_fields,
    case_target_profile,
    consolidate_identities,
    prune_unlinked_entities,
    confirm_entity,
    create_manual_edge,
    delete_case_note,
    delete_edge,
    detach_entities,
    detach_entity,
    delete_edges,
    enrich_entity,
    entity_id_fields,
    enqueue_expand,
    find_entity_by_key,
    enqueue_qsa_network,
    graph_counts,
    graph_payload,
    job_counts,
    requeue_stale_running_jobs,
    save_graph_layout,
    list_notes,
    note_tree,
    purge_investigation,
    update_edge,
)
from osint4all.connectors.base import FoundEntity
from osint4all.graph.expand import process_pending_jobs
from osint4all.graph.resolve import apply_result, upsert_found_entity
from osint4all.consult import MODES, ConsultResult, public_ficha, run_consult
from osint4all.graph.identity import MAX_GRAPH_DEPTH, seed_fits_profile
from osint4all.graph.layers import ALVO_GROUPS, confirmed_seeds, qsa_confirms_name, run_alvo_layer
from osint4all.graph.media import collect_target_media, fields_from_identifiers
from osint4all.graph.seed import add_seed_entities, attach_person_profile, attach_plate_owner, create_investigation
from osint4all.tools_suite import (
    MassResult,
    get_tool,
    graph_tools_plan,
    list_tools,
    outcome_to_connector,
    run_embedded_tool,
    run_mass,
    seeds_from_results,
    tool_id_for_kind,
)
from osint4all.identifiers import collect_form_seeds, parse_seed
from osint4all.validators import looks_like_plate, validate_cnpj
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


def _set_flash(request: Request, level: str, message: str) -> None:
    request.session["flash"] = {"level": level, "message": message}


def _host_cards_for(session: Session, investigation_id: str, entity: Entity) -> list:
    from osint4all.intel.hosts import cards_for_entity

    return cards_for_entity(session, investigation_id, entity)


def _case_events(session: Session, investigation_id: str, entity_id: str | None = None, limit: int = 40):
    from osint4all.quality.timeline import list_events

    return list_events(session, investigation_id, entity_id=entity_id, limit=limit)


def _case_tasks(session: Session, investigation_id: str):
    from osint4all.quality.tasks import list_tasks

    return list_tasks(session, investigation_id)


def _case_changes(session: Session, investigation_id: str):
    from osint4all.quality.changes import recent_changes

    return recent_changes(session, investigation_id, limit=12)


def _case_digest(session: Session, investigation_id: str):
    from osint4all.quality.changes import case_digest

    return case_digest(session, investigation_id)


def _source_errors(session: Session, investigation_id: str):
    from osint4all.quality.health import recent_job_errors

    return recent_job_errors(session, investigation_id)


def _resolution(entity: Entity):
    from osint4all.quality.resolution import resolution_score

    return resolution_score(entity)


def _parse_retain(raw: str):
    from datetime import datetime, timezone

    text = (raw or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _sync_expand(investigation_id: str, *, rounds: int = 1) -> int:
    settings = get_settings()
    if not settings.expand_sync:
        return 0
    processed = 0
    for _ in range(max(1, rounds)):
        n = process_pending_jobs(investigation_id=investigation_id, limit=settings.expand_sync_limit, settings=settings)
        if not n:
            break
        processed += n
    return processed


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept.split(",")[0]


def _safe_next(investigation_id: str, next_url: str, fallback: str) -> str:
    prefix = f"/app/casos/{investigation_id}"
    target = (next_url or "").strip()
    if target.startswith(prefix + "/") or target == prefix:
        return target
    return fallback


def _case_pulse(session: Session, investigation_id: str) -> dict:
    requeue_stale_running_jobs(session, investigation_id)
    counts = job_counts(session, investigation_id)
    counts.update(graph_counts(session, investigation_id))
    queue = (counts.get("PENDING") or 0) + (counts.get("RUNNING") or 0)
    if counts.get("RUNNING"):
        counts["phase"] = "loading"
        counts["label"] = (
            f"Rodando… {counts['RUNNING']} em curso, {counts.get('PENDING') or 0} na fila "
            f"· {counts['entities']} nós"
        )
    elif counts.get("PENDING"):
        counts["phase"] = "loading"
        counts["label"] = f"Na fila: {counts['PENDING']} consulta(s) · {counts['entities']} nós no grafo"
    else:
        counts["phase"] = "ok"
        counts["label"] = f"Concluído · {counts['entities']} nós · {counts['edges']} vínculos"
    counts["queue"] = queue
    return counts


def _json_case(session: Session, investigation_id: str, **extra) -> JSONResponse:
    payload = _case_pulse(session, investigation_id)
    payload.update(extra)
    return JSONResponse(payload)


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
    enqueue: bool = False,
) -> int:
    seeds = seeds_from_results(parts)
    profile = case_target_profile(session, inv.id)
    seeds = [item for item in seeds if seed_fits_profile(item.kind, item.value, item.display_name, profile)]
    if not seeds:
        return 0
    add_seed_entities(session, inv, seeds, max_attempts=get_settings().job_max_attempts, enqueue=enqueue)
    plate = next((s for s in seeds if s.kind == "PLATE"), None)
    if plate and owner.strip():
        attach_plate_owner(
            session,
            inv,
            plate=plate.value,
            owner_name=owner.strip(),
            max_attempts=get_settings().job_max_attempts,
        )
    if enqueue:
        _sync_expand(inv.id)
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
        hypothesis="Gerada a partir desta consulta. Expanda no grafo só o que validar.",
        seeds=seeds,
        connectors=list(enabled_connector_names()),
        max_depth=get_settings().default_max_depth,
        monitor=False,
        created_by=user.username,
        max_attempts=get_settings().job_max_attempts,
        enqueue=False,
    )
    write_audit(session, "investigation.from_chain", username=user.username, investigation_id=inv.id, details={"steps": len(seeds)})
    session.commit()
    request.session["current_case_id"] = inv.id
    _set_flash(
        request,
        "ok",
        f"Caso «{inv.title}» criado com {len(seeds)} identificador(es) desta consulta. "
        "Nada foi expandido — use Procurar ou Explodir QSA no grafo.",
    )
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
    layer.fields = save_alvo_fields(session, user, layer.fields)
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
    request.session["flash"] = {
        "level": "ok" if layer.ok else "error",
        "message": (
            f"Camada {kind} carregada."
            if layer.ok
            else f"Camada {kind} sem resultado nesta passagem."
        ),
    }
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


@router.post("/app/alvo/limpar")
def alvo_clear(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    reset_alvo_draft(session, user)
    request.session.pop("alvo_qsa_match", None)
    write_audit(session, "alvo.reset", username=user.username)
    request.session["flash"] = {"level": "ok", "message": "Alvo limpo. As camadas não vão para nenhum caso até você atribuir."}
    return RedirectResponse("/app/alvo", status_code=303)


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
    target_id = (investigation_id or "").strip()
    inv = session.get(Investigation, target_id) if target_id else None
    created = False
    if inv:
        add_seed_entities(session, inv, seeds, max_attempts=get_settings().job_max_attempts, enqueue=False)
        write_audit(session, "investigation.from_alvo", username=user.username, investigation_id=inv.id, details={"added": len(seeds)})
    else:
        name = fields.get("NAME") or seeds[0].display_name
        inv = create_investigation(
            session,
            title=f"Alvo · {name}",
            hypothesis="Dossiê do alvo em camadas. Só o que você validou. Expanda no grafo depois.",
            seeds=seeds,
            connectors=list(enabled_connector_names()),
            max_depth=4,
            monitor=False,
            created_by=user.username,
            max_attempts=get_settings().job_max_attempts,
            enqueue=False,
        )
        write_audit(session, "investigation.from_alvo", username=user.username, investigation_id=inv.id, details={"seeds": len(seeds)})
        created = True
    session.commit()
    request.session["current_case_id"] = inv.id
    _set_flash(
        request,
        "ok",
        (
            f"Caso «{inv.title}» criado só com {len(seeds)} identificador(es) que você validou."
            if created
            else f"{len(seeds)} identificador(es) validados adicionados a «{inv.title}»."
        )
        + " Nada foi expandido automaticamente — use Procurar ou Explodir QSA.",
    )
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
    parts = []
    if value:
        parts.append(ConsultResult(kind=kind, query=value, title=value, summary="", ok=True))
    for item_kind, item_value in zip(kinds, values, strict=False):
        if item_value:
            parts.append(ConsultResult(kind=item_kind, query=item_value, title=item_value, summary="", ok=True))
    seeds = seeds_from_results(parts)
    if not seeds:
        _set_flash(request, "error", "Não deu para abrir o grafo com esse valor.")
        return RedirectResponse("/app", status_code=303)
    seed = seeds[0]
    inv = create_investigation(
        session,
        title=f"Consulta · {seed.display_name}",
        hypothesis="Gerada a partir de uma consulta rápida. Expanda no grafo só o que validar.",
        seeds=seeds,
        connectors=list(enabled_connector_names()),
        max_depth=get_settings().default_max_depth,
        monitor=False,
        created_by=user.username,
        max_attempts=get_settings().job_max_attempts,
        enqueue=False,
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
    _set_flash(
        request,
        "ok",
        f"Caso «{inv.title}» criado só com este resultado. Nada foi expandido automaticamente.",
    )
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
    target_id = (investigation_id or "").strip()
    inv = session.get(Investigation, target_id) if target_id else None
    if not inv:
        _set_flash(request, "error", "Escolha o caso na lista. Nada vai sozinho para o caso anterior.")
        return RedirectResponse("/app", status_code=303)
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
    if added:
        _set_flash(request, "ok", f"{added} identificador(es) adicionados a {inv.title}.")
    else:
        _set_flash(request, "error", "Nenhum identificador válido para acrescentar a este caso.")
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
            "source_catalog": SOURCE_CATALOG,
            "enabled": enabled_connector_names(settings),
            "default_depth": settings.default_max_depth,
            "playbooks": ("PERSON", "COMPANY"),
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
    seed_cnj: str = Form(""),
    seed_birth: str = Form(""),
    seed_father: str = Form(""),
    seed_mother: str = Form(""),
    max_depth: int = Form(2),
    monitor: str = Form(""),
    connectors: list[str] = Form(default=[]),
    purpose: str = Form(""),
    assignee: str = Form(""),
    playbook_key: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    parsed = collect_form_seeds(
        seeds,
        seed_cpf=seed_cpf,
        seed_cnpj=seed_cnpj,
        seed_name=seed_name,
        seed_email=seed_email,
        seed_phone=seed_phone,
        seed_username=seed_username,
        seed_plate=seed_plate,
        seed_plate_owner=seed_plate_owner,
        seed_plate_cpf=seed_plate_cpf,
        seed_cnj=seed_cnj,
        seed_birth=seed_birth,
        seed_father=seed_father,
        seed_mother=seed_mother,
    )
    if not parsed:
        _set_flash(request, "error", "Informe ao menos uma semente válida.")
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
    inv.purpose = purpose.strip() or None
    inv.assignee = assignee.strip() or user.username
    if playbook_key.upper() in {"COMPANY", "PERSON"}:
        from osint4all.engines.playbooks import attach_playbook

        attach_playbook(session, inv, playbook_key.upper())
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
    request.session["current_case_id"] = inv.id
    processed = _sync_expand(inv.id)
    _set_flash(
        request,
        "ok",
        (
            f"Caso «{inv.title}» criado com {len(parsed)} identificador(es). "
            + (f"{processed} lote(s) carregado(s)." if processed else "Fontes em carga.")
        ),
    )
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


def _case_company(session: Session, investigation_id: str) -> str:
    for entity in session.scalars(
        select(Entity)
        .where(Entity.investigation_id == investigation_id, Entity.entity_type == "ORG")
        .order_by(Entity.is_seed.desc(), Entity.display_name)
    ):
        name = (entity.display_name or "").strip()
        if len(name) >= 3 and not name.isdigit() and not validate_cnpj(name):
            return name
    return ""


def _case_person(session: Session, investigation_id: str) -> str:
    for entity in session.scalars(
        select(Entity)
        .where(Entity.investigation_id == investigation_id, Entity.entity_type == "PERSON")
        .order_by(Entity.is_seed.desc(), Entity.display_name)
    ):
        name = (entity.display_name or "").strip()
        if name.count(" ") >= 1 and len(name) >= 5:
            return name
    return ""


def _media_page(request: Request, user: User, fields: dict[str, str], *, title: str = "") -> HTMLResponse:
    media = collect_target_media(fields=fields, title=title)
    ctx = template_context(request, user)
    ctx["media"] = media
    return templates.TemplateResponse(request, "app/media_panel.html", ctx)


@router.get("/app/alvo/midia", response_class=HTMLResponse)
def alvo_media(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    return _media_page(request, user, alvo_fields(session, user))


@router.get("/app/casos/{investigation_id}/midia", response_class=HTMLResponse)
def case_media(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    inv = session.get(Investigation, investigation_id)
    if not inv:
        ctx = template_context(request, user)
        ctx["media"] = collect_target_media([])
        ctx["media"].notes = ["Investigação não encontrada."]
        return templates.TemplateResponse(request, "app/media_panel.html", ctx, status_code=404)
    fields = fields_from_identifiers(
        case_identifiers(session, inv.id),
        company=_case_company(session, inv.id),
        name=_case_person(session, inv.id),
    )
    return _media_page(request, user, fields, title=inv.title or "")


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
    dossier = case_identifiers(session, inv.id)
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
                select(Entity)
                .options(load_only(Entity.id, Entity.display_name))
                .where(Entity.investigation_id == inv.id)
                .order_by(Entity.display_name)
            ).all(),
            "rel_types": EDGE_REL_TYPES,
            "dossier": dossier,
            "graph_tools": graph_tools_plan(dossier),
            "target": case_target_fields(session, inv.id),
            "case_events": _case_events(session, inv.id, limit=20),
            "case_tasks": _case_tasks(session, inv.id),
            "case_changes": _case_changes(session, inv.id),
            "case_digest": _case_digest(session, inv.id),
            "source_errors": _source_errors(session, inv.id),
            "case_statuses": ("ACTIVE", "DRAFT", "INVESTIGATING", "REVIEW", "VERIFIED", "PUBLISHED", "CLOSED", "ARCHIVED"),
        }
    )
    from osint4all.engines.playbooks import list_items, progress

    ctx["playbook_progress"] = progress(list_items(session, inv.id, inv.playbook_key))
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
    seeds: str = Form(""),
    seed_cpf: str = Form(""),
    seed_cnpj: str = Form(""),
    seed_name: str = Form(""),
    seed_email: str = Form(""),
    seed_phone: str = Form(""),
    seed_username: str = Form(""),
    seed_plate: str = Form(""),
    seed_plate_owner: str = Form(""),
    seed_cnj: str = Form(""),
    seed_birth: str = Form(""),
    seed_father: str = Form(""),
    seed_mother: str = Form(""),
    purpose: str = Form(""),
    assignee: str = Form(""),
    classification: str = Form("interno"),
    retain_until: str = Form(""),
    case_status: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    if title.strip():
        inv.title = title.strip()[:255]
    inv.hypothesis = hypothesis.strip() or None
    inv.purpose = purpose.strip() or None
    inv.assignee = assignee.strip() or inv.assignee
    inv.classification = (classification or "interno").strip()[:32] or "interno"
    inv.retain_until = _parse_retain(retain_until)
    if case_status in {"ACTIVE", "DRAFT", "INVESTIGATING", "REVIEW", "VERIFIED", "PUBLISHED", "CLOSED", "ARCHIVED"}:
        inv.status = case_status
        inv.workflow = case_status if case_status != "ACTIVE" else "INVESTIGATING"
    inv.max_depth = max(0, min(max_depth, MAX_GRAPH_DEPTH))
    incoming = collect_form_seeds(
        seeds,
        seed_cpf=seed_cpf,
        seed_cnpj=seed_cnpj,
        seed_name=seed_name,
        seed_email=seed_email,
        seed_phone=seed_phone,
        seed_username=seed_username,
        seed_plate=seed_plate,
        seed_plate_owner=seed_plate_owner,
        seed_cnj=seed_cnj,
        seed_birth=seed_birth,
        seed_father=seed_father,
        seed_mother=seed_mother,
    )
    known = case_known_keys(session, inv.id)
    profile = case_target_profile(session, inv.id)
    fresh = [
        item
        for item in incoming
        if item.canonical_key not in known and seed_fits_profile(item.kind, item.value, item.display_name, profile)
    ]
    if fresh:
        add_seed_entities(session, inv, fresh, max_attempts=get_settings().job_max_attempts, force=True)
    if seed_birth.strip() or seed_father.strip() or seed_mother.strip():
        attach_person_profile(
            session,
            inv,
            birth=seed_birth,
            father=seed_father,
            mother=seed_mother,
            name=seed_name,
            cpf=seed_cpf,
        )
    if looks_like_plate(seed_plate):
        attach_plate_owner(
            session,
            inv,
            plate=seed_plate,
            owner_name=seed_plate_owner,
            max_attempts=get_settings().job_max_attempts,
        )
    queued = 0
    if fresh:
        queued = enqueue_qsa_network(session, inv, max_attempts=get_settings().job_max_attempts)
    write_audit(
        session,
        "investigation.edit",
        username=user.username,
        investigation_id=inv.id,
        details={"added": len(fresh), "queued": queued},
    )
    session.commit()
    processed = _sync_expand(inv.id) if fresh else 0
    if fresh:
        extra = (
            f"{processed} lote(s) reprocessados — o grafo procura ligações que as infos novas abrem."
            if processed
            else "Fontes em carga para fechar ligações faltantes."
        )
        message = f"Caso atualizado. {len(fresh)} identificador(es) novo(s). {extra}"
    else:
        message = "Caso atualizado."
    _set_flash(request, "ok", message)
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


@router.post("/app/casos/{investigation_id}/grafo/layout")
async def graph_layout_save(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "JSON inválido"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"detail": "JSON inválido"}, status_code=400)
    require_csrf(request, str(data.get("csrf_token") or request.headers.get("x-csrf-token") or ""))
    layout = save_graph_layout(session, investigation_id, data)
    if layout is None:
        return JSONResponse({"detail": "caso não encontrado"}, status_code=404)
    return JSONResponse({"ok": True, "nodes": len(layout.get("nodes") or {})})


@router.get("/app/casos/{investigation_id}/status")
def job_status(
    investigation_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> JSONResponse:
    return JSONResponse(_case_pulse(session, investigation_id))


@router.post("/app/casos/{investigation_id}/tick")
def tick_case(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> JSONResponse:
    require_csrf(request, csrf_token)
    if not session.get(Investigation, investigation_id):
        return JSONResponse({"ok": False, "error": "caso não encontrado"}, status_code=404)
    processed = process_pending_jobs(investigation_id=investigation_id, limit=3, settings=get_settings())
    session.expire_all()
    return _json_case(session, investigation_id, ok=True, processed=processed)


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
        _set_flash(request, "error", "Entidade não encontrada neste caso.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    from osint4all.engines.intelligence import cross_case_hits
    from osint4all.engines.knowledge import is_stale, versions_for
    from osint4all.engines.verification import entity_pii
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
            "host_cards": _host_cards_for(session, investigation_id, entity),
            "resolution": _resolution(entity),
            "case_events": _case_events(session, investigation_id, entity.id),
            "verdicts": (("confirmed", "Confirmado"), ("probable", "Provável"), ("unconfirmed", "Não confirmado"), ("contested", "Contestado"), ("false", "Falso")),
            "versions": versions_for(session, entity.id),
            "pii_class": entity_pii(entity),
            "stale": is_stale(entity),
            "cross_hits": [h for h in cross_case_hits(session, investigation_id) if h["key"] == entity.canonical_key],
            "id_fields": entity_id_fields(entity),
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
        _set_flash(request, "error", "Não foi possível expandir este nó.")
        return RedirectResponse("/app", status_code=303)
    enqueue_expand(
        session,
        investigation=inv,
        entity=entity,
        depth=entity.depth,
        max_attempts=get_settings().job_max_attempts,
        force=True,
    )
    write_audit(
        session,
        "entity.expand",
        username=user.username,
        investigation_id=inv.id,
        details={"entity_id": entity.id},
    )
    session.commit()
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, queued=True)
    _set_flash(request, "ok", f"Expansão de «{entity.display_name}» na fila. O grafo atualiza sozinho.")
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/procurar")
def probe_node(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    kind: str = Form(""),
    kinds: list[str] = Form(default=[]),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    entity = session.get(Entity, entity_id)
    if not inv or not entity or entity.investigation_id != inv.id:
        _set_flash(request, "error", "Não foi possível procurar neste nó.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    selected = [str(item).strip().upper() for item in list(kinds or []) + ([kind] if kind else []) if str(item).strip()]
    selected = list(dict.fromkeys(selected))
    if selected:
        attrs = dict(entity.attrs or {})
        attrs["probe_kinds"] = selected
        entity.attrs = attrs
    enqueue_expand(
        session,
        investigation=inv,
        entity=entity,
        depth=entity.depth,
        max_attempts=get_settings().job_max_attempts,
        force=True,
    )
    write_audit(
        session,
        "entity.probe",
        username=user.username,
        investigation_id=inv.id,
        details={"entity_id": entity.id, "name": entity.display_name, "kinds": selected or [kind]},
    )
    session.commit()
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, queued=True)
    _set_flash(request, "ok", f"Busca de «{entity.display_name}» na fila. O grafo atualiza sozinho.")
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


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
    seed_cpf: str = Form(""),
    seed_email: str = Form(""),
    seed_phone: str = Form(""),
    seed_username: str = Form(""),
    seed_birth: str = Form(""),
    seed_father: str = Form(""),
    seed_mother: str = Form(""),
    depois: str = Form("gravar"),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    entity = session.scalar(
        select(Entity)
        .options(selectinload(Entity.identifiers))
        .where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not entity:
        _set_flash(request, "error", "Entidade não encontrada neste caso.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    if display_name.strip():
        entity.display_name = display_name.strip()[:512]
    attrs = dict(entity.attrs or {})
    if note.strip():
        attrs["nota"] = note.strip()[:2000]
    elif "nota" in attrs and not note.strip():
        attrs.pop("nota", None)
    entity.attrs = attrs
    seeds = collect_form_seeds(
        seed_cpf=seed_cpf,
        seed_email=seed_email,
        seed_phone=seed_phone,
        seed_username=seed_username,
        seed_birth=seed_birth,
        seed_father=seed_father,
        seed_mother=seed_mother,
        seed_name=display_name,
    )
    kinds = enrich_entity(entity, seeds)
    inv = session.get(Investigation, investigation_id)
    if depois == "buscar" and inv:
        probe = [item for item in kinds if item in {"EMAIL", "USERNAME", "PHONE", "CPF", "NAME", "CNPJ"}]
        if probe:
            attrs = dict(entity.attrs or {})
            attrs["probe_kinds"] = probe
            entity.attrs = attrs
        enqueue_expand(session, investigation=inv, entity=entity, depth=entity.depth, max_attempts=get_settings().job_max_attempts, force=True)
    write_audit(session, "entity.edit", username=user.username, investigation_id=investigation_id, details={"entity_id": entity.id, "kinds": kinds})
    session.commit()
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, kinds=kinds, queued=depois == "buscar")
    _set_flash(
        request,
        "ok",
        "Dados gravados na ficha. A próxima busca usa CPF/e-mail/@ e evita homônimo."
        if depois != "buscar"
        else "Dados gravados. Busca precisa na fila — o grafo atualiza sozinho.",
    )
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
        _set_flash(request, "error", "Entidade não encontrada neste caso.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    confirm_entity(session, entity, reason="Confirmado na ficha do alvo.")
    inv = session.get(Investigation, investigation_id)
    if inv:
        enqueue_expand(session, investigation=inv, entity=entity, depth=entity.depth, max_attempts=get_settings().job_max_attempts)
    write_audit(session, "entity.confirm", username=user.username, investigation_id=investigation_id, details={"entity_id": entity_id})
    session.commit()
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, confirmed=True)
    _set_flash(request, "ok", "Nó confirmado. A próxima camada pode expandir daqui.")
    return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/verificar")
def verify_node(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    verdict: str = Form("unconfirmed"),
    reason: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    entity = session.scalar(select(Entity).where(Entity.id == entity_id, Entity.investigation_id == investigation_id))
    inv = session.get(Investigation, investigation_id)
    if not entity or not inv:
        _set_flash(request, "error", "Entidade não encontrada neste caso.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    from osint4all.quality.timeline import add_event
    from osint4all.quality.verification import apply_verdict, verdict_label

    apply_verdict(session, inv, entity, verdict=verdict, reason=reason, created_by=user.username)
    add_event(session, inv, event_type="verdict", title=verdict_label(verdict), meta=reason[:400], entity_id=entity.id)
    if verdict == "confirmed":
        enqueue_expand(session, investigation=inv, entity=entity, depth=entity.depth, max_attempts=get_settings().job_max_attempts)
    write_audit(session, "entity.verify", username=user.username, investigation_id=investigation_id, details={"entity_id": entity_id, "verdict": verdict})
    session.commit()
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, verdict=verdict)
    _set_flash(request, "ok", f"Veredito: {verdict_label(verdict)}.")
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
        if _wants_json(request):
            return _json_case(session, investigation_id, ok=True, removed=True)
        _set_flash(request, "ok", "Nó desligado. Pessoas e empresas que só existiam por ele saíram do caso.")
    else:
        if _wants_json(request):
            return _json_case(session, investigation_id, ok=False, error="Esse nó já não está no caso.")
        _set_flash(request, "error", "Esse nó já não está no caso.")
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/entidades/lote/desligar")
def detach_nodes(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    entity_ids: list[str] = Form(default=[]),
    next: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "caso não encontrado"}, status_code=404)
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    removed = detach_entities(session, investigation_id, [item for item in entity_ids if item], keep_seeds=True)
    write_audit(session, "entity.detach_batch", username=user.username, investigation_id=investigation_id, details={"removed": removed})
    session.commit()
    dest = _safe_next(investigation_id, next, f"/app/casos/{investigation_id}")
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, removed=removed)
    _set_flash(request, "ok", f"{removed} nó(s) removidos. O alvo permanece.")
    return RedirectResponse(dest, status_code=303)


@router.post("/app/casos/{investigation_id}/ligacoes/lote/apagar")
def remove_links(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    edge_ids: list[str] = Form(default=[]),
    entity_ids: list[str] = Form(default=[]),
    from_id: str = Form(""),
    next: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "caso não encontrado"}, status_code=404)
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    wanted = [item for item in edge_ids if item]
    peers = [item for item in entity_ids if item]
    if from_id and peers:
        wanted.extend(
            str(item)
            for item in session.scalars(
                select(Edge.id).where(
                    Edge.investigation_id == investigation_id,
                    or_(
                        and_(Edge.from_entity_id == from_id, Edge.to_entity_id.in_(peers)),
                        and_(Edge.to_entity_id == from_id, Edge.from_entity_id.in_(peers)),
                    ),
                )
            )
        )
    removed = delete_edges(session, investigation_id, wanted)
    write_audit(session, "edge.delete_batch", username=user.username, investigation_id=investigation_id, details={"removed": removed})
    session.commit()
    dest = _safe_next(investigation_id, next, f"/app/casos/{investigation_id}")
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, removed=removed)
    _set_flash(request, "ok", f"{removed} ligação(ões) apagadas. Os nós continuam no caso.")
    return RedirectResponse(dest, status_code=303)


@router.post("/app/casos/{investigation_id}/entidades/{entity_id}/pessoa")
def add_person_to_node(
    investigation_id: str,
    entity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    seed_name: str = Form(""),
    seed_cpf: str = Form(""),
    seed_email: str = Form(""),
    seed_phone: str = Form(""),
    seed_username: str = Form(""),
    depois: str = Form("gravar"),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    host = session.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not inv or not host:
        _set_flash(request, "error", "Não foi possível acrescentar a pessoa.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    seeds = collect_form_seeds(
        seed_name=seed_name,
        seed_cpf=seed_cpf,
        seed_email=seed_email,
        seed_phone=seed_phone,
        seed_username=seed_username,
    )
    person_seed = next((item for item in seeds if item.kind in {"CPF", "NAME"}), None)
    if not person_seed:
        _set_flash(request, "error", "Informe o nome ou o CPF da pessoa.")
        return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity_id}", status_code=303)
    person = upsert_found_entity(
        session,
        inv,
        FoundEntity(
            entity_type="PERSON",
            kind=person_seed.kind,
            value=person_seed.value,
            display_name=person_seed.display_name,
            confidence=0.99 if person_seed.kind == "CPF" else 0.7,
        ),
        depth=max(1, (host.depth or 0) + 1),
        is_seed=False,
    )
    person = session.scalar(select(Entity).options(selectinload(Entity.identifiers)).where(Entity.id == person.id))
    kinds = enrich_entity(person, seeds) if person else []
    if person and person.id != host.id:
        create_manual_edge(session, inv, from_id=host.id, to_id=person.id, rel_type="SOCIO", note="Pessoa acrescentada na ficha")
    if depois == "buscar" and person:
        probe = [item for item in kinds if item in {"EMAIL", "USERNAME", "PHONE", "CPF", "NAME"}]
        if probe:
            attrs = dict(person.attrs or {})
            attrs["probe_kinds"] = probe
            person.attrs = attrs
        enqueue_expand(session, investigation=inv, entity=person, depth=person.depth, max_attempts=get_settings().job_max_attempts, force=True)
    write_audit(session, "entity.add_person", username=user.username, investigation_id=inv.id, details={"host": host.id, "person": person.id if person else ""})
    session.commit()
    dest = f"/app/casos/{investigation_id}/entidades/{person.id}" if person else f"/app/casos/{investigation_id}/entidades/{entity_id}"
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, queued=depois == "buscar")
    _set_flash(request, "ok", "Pessoa ligada. Complete CPF/e-mail/@ na ficha antes de buscar de novo.")
    return RedirectResponse(dest, status_code=303)


@router.post("/app/casos/{investigation_id}/empresas")
def add_company(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    cnpj: str = Form(""),
    from_id: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "caso não encontrado"}, status_code=404)
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    seed = parse_seed(cnpj, forced_kind="CNPJ")
    if not seed:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "CNPJ inválido"}, status_code=400)
        _set_flash(request, "error", "Informe um CNPJ válido.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    org = find_entity_by_key(session, inv.id, seed.canonical_key)
    if not org:
        org = upsert_found_entity(
            session,
            inv,
            FoundEntity(
                entity_type="ORG",
                kind="CNPJ",
                value=seed.value,
                display_name=seed.display_name,
                confidence=0.99,
            ),
            depth=1,
            is_seed=False,
        )
    attrs = dict(org.attrs or {})
    attrs["probe_kinds"] = ["QSA"]
    org.attrs = attrs
    enqueue_expand(session, investigation=inv, entity=org, depth=org.depth, max_attempts=get_settings().job_max_attempts, force=True)
    source = session.get(Entity, from_id) if from_id else None
    if source and source.investigation_id == inv.id and source.id != org.id:
        create_manual_edge(session, inv, from_id=source.id, to_id=org.id, rel_type="EMPRESA", note="CNPJ acrescentado no grafo")
    write_audit(session, "investigation.add_company", username=user.username, investigation_id=inv.id, details={"cnpj": seed.display_name})
    session.commit()
    if _wants_json(request):
        return _json_case(session, investigation_id, ok=True, queued=True)
    _set_flash(request, "ok", "Empresa ligada ao alvo. QSA e sócios entram na fila.")
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.post("/app/casos/{investigation_id}/buscar-ferramentas")
def search_graph_tools(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    tools: list[str] = Form(default=[]),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    selected = [str(item).strip().lower() for item in tools if str(item).strip()]
    plan = {item["id"]: item for item in graph_tools_plan(case_identifiers(session, inv.id))}
    ran = 0
    added = 0
    errors: list[str] = []
    for tool_id in selected:
        item = plan.get(tool_id)
        if not item or not item.get("ready"):
            continue
        for raw in item["values"]:
            try:
                outcome = run_embedded_tool(tool_id, raw)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{item['name']}: {exc}")
                continue
            seed = parse_seed(raw)
            origin = find_entity_by_key(session, inv.id, seed.canonical_key) if seed else None
            if origin is None:
                origin = session.scalar(
                    select(Entity).where(Entity.investigation_id == inv.id, Entity.is_seed.is_(True))
                )
            if origin is None:
                errors.append(f"{item['name']}: sem nó de origem no grafo.")
                continue
            result = outcome_to_connector(outcome, origin.canonical_key)
            created = apply_result(
                session,
                inv,
                origin,
                result,
                connector=f"tool:{tool_id}",
                depth=origin.depth or 0,
                enqueue_children=False,
                max_attempts=get_settings().job_max_attempts,
                fill_only=True,
                consolidate=False,
            )
            ran += 1
            added += len(created)
            if not getattr(outcome, "ok", True) and getattr(outcome, "error", None):
                errors.append(f"{item['name']}: {outcome.error}")
    if ran:
        consolidate_identities(session, inv.id)
    write_audit(
        session,
        "investigation.graph_tools",
        username=user.username,
        investigation_id=inv.id,
        details={"tools": selected, "ran": ran, "added": added},
    )
    session.commit()
    if _wants_json(request):
        return _json_case(session, inv.id, ok=True, ran=ran, added=added)
    if ran:
        extra = f" {errors[0]}" if errors else ""
        _set_flash(
            request,
            "ok",
            f"Busca complementar: {ran} consulta(s), {added} info(s) nova(s) no grafo (nada foi substituído).{extra}",
        )
    else:
        _set_flash(request, "error", errors[0] if errors else "Marque ao menos uma ferramenta com dado já no grafo.")
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


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
        _set_flash(request, "error", "Investigação não encontrada.")
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
    if _wants_json(request):
        return _json_case(session, inv.id, ok=True, queued=queued)
    _set_flash(
        request,
        "ok",
        f"QSA em cadeia até grau {inv.max_depth}: {queued} âncora(s) na fila. O grafo atualiza sozinho.",
    )
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.post("/app/casos/{investigation_id}/processar")
def process_now(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    processed = process_pending_jobs(investigation_id=investigation_id, limit=3, settings=get_settings())
    session.expire_all()
    pulse = _case_pulse(session, investigation_id)
    if _wants_json(request):
        pulse.update({"ok": True, "processed": processed})
        return JSONResponse(pulse)
    queue = pulse.get("queue") or 0
    _set_flash(
        request,
        "ok",
        (
            f"Processamento concluído: {processed} lote(s)."
            if queue == 0
            else f"{processed} lote(s) processado(s). Ainda há {queue} na fila — o grafo segue atualizando."
        ),
    )
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
    kind: str = Form("note"),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    add_case_note(
        session,
        inv,
        title=title,
        body=body,
        entity_id=entity_id or None,
        parent_id=parent_id or None,
        created_by=user.username,
        on_graph=bool(on_graph) or kind == "diagram",
        kind=kind,
    )
    write_audit(session, "note.add", username=user.username, investigation_id=inv.id, details={"on_graph": bool(on_graph), "kind": kind})
    session.commit()
    request.session["flash"] = {
        "level": "ok",
        "message": "Diagrama colocado no grafo." if kind == "diagram" else "Anotação gravada no caso.",
    }
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.post("/app/casos/{investigation_id}/tarefas")
def add_task_route(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    title: str = Form(""),
    body: str = Form(""),
    assignee: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if not inv:
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    from osint4all.quality.tasks import add_task
    from osint4all.quality.timeline import add_event

    add_task(session, inv, title=title, body=body, assignee=assignee or user.username, created_by=user.username)
    add_event(session, inv, event_type="task", title=title or "Tarefa", meta=assignee or user.username)
    write_audit(session, "task.add", username=user.username, investigation_id=inv.id, details={"title": title})
    session.commit()
    _set_flash(request, "ok", "Tarefa adicionada ao caso.")
    return RedirectResponse(f"/app/casos/{inv.id}", status_code=303)


@router.post("/app/casos/{investigation_id}/tarefas/{task_id}/estado")
def toggle_task_route(
    investigation_id: str,
    task_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    done: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    from osint4all.quality.tasks import set_task_status

    row = set_task_status(session, investigation_id, task_id, done=done == "1")
    if row:
        write_audit(session, "task.toggle", username=user.username, investigation_id=investigation_id, details={"task_id": task_id, "done": done})
        session.commit()
        _set_flash(request, "ok", "Tarefa atualizada.")
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


@router.get("/app/casos/{investigation_id}/evidencias/{evidence_id}/captura")
def evidence_capture(
    investigation_id: str,
    evidence_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    ev = session.scalar(select(Evidence).where(Evidence.id == evidence_id, Evidence.investigation_id == investigation_id))
    if not ev or not ev.raw_path:
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    from osint4all.quality.provenance import snapshot_abs

    path = snapshot_abs(ev.raw_path)
    if not path:
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    return FileResponse(path)


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
        _set_flash(request, "ok", "Anotação removida.")
    else:
        _set_flash(request, "error", "Essa anotação já não existe.")
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
        _set_flash(request, "error", "Investigação não encontrada.")
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
        _set_flash(request, "error", "Ligação não encontrada.")
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    src = session.get(Entity, edge.from_entity_id)
    dst = session.get(Entity, edge.to_entity_id)
    ctx = template_context(request, user)
    from osint4all.engines.knowledge import annotate_edge

    why = annotate_edge(edge)
    related = []
    for ev in session.scalars(select(Evidence).where(Evidence.investigation_id == investigation_id)).all():
        if ev.entity_id in {edge.from_entity_id, edge.to_entity_id}:
            related.append(ev)
    ctx.update(
        {
            "nav": "casos",
            "inv": inv,
            "edge": edge,
            "src": src,
            "dst": dst,
            "rel_types": EDGE_REL_TYPES,
            "why": why,
            "edge_evidence": related[:12],
        }
    )
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
    period: str = Form(""),
    strength: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    edge = update_edge(session, investigation_id, edge_id, rel_type=rel_type, note=note, period=period, strength=strength)
    if edge:
        write_audit(session, "edge.edit", username=user.username, investigation_id=investigation_id, details={"rel": rel_type})
        session.commit()
        _set_flash(request, "ok", "Ligação atualizada.")
        return RedirectResponse(f"/app/casos/{investigation_id}/ligacoes/{edge_id}", status_code=303)
    _set_flash(request, "error", "Não foi possível atualizar: já existe uma ligação desse tipo ou ela sumiu.")
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
        if _wants_json(request):
            return _json_case(session, investigation_id, ok=True, removed=True)
        _set_flash(request, "ok", "Ligação removida. Os nós continuam no caso.")
    else:
        if _wants_json(request):
            return _json_case(session, investigation_id, ok=False, error="Essa ligação já não existe.")
        _set_flash(request, "error", "Essa ligação já não existe.")
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
    _sync_expand(inv.id)
    _set_flash(request, "ok", "Veículo adicionado ao grafo.")
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


_MAX_FILE_BYTES = 8 * 1024 * 1024
_DOC_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}


def _file_kind(name: str, data: bytes) -> str | None:
    suffix = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if suffix == "pdf" or data.startswith(b"%PDF"):
        return "pdf"
    if suffix == "png" or data.startswith(b"\x89PNG"):
        return "png"
    if suffix in {"jpg", "jpeg"} or data.startswith(b"\xff\xd8"):
        return "jpeg"
    return None


@router.post("/app/casos/{investigation_id}/documento")
async def attach_document(
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
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in _DOC_SUFFIXES:
        request.session["flash"] = {"level": "error", "message": "Envie PDF, JPEG ou PNG (máx. 8 MB)."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    data = await arquivo.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        request.session["flash"] = {"level": "error", "message": "Arquivo acima de 8 MB."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    if not _file_kind(name, data):
        request.session["flash"] = {"level": "error", "message": "Arquivo não parece PDF, JPEG ou PNG."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    entity = ingest_local_file(session, inv, filename=name, data=data)
    write_audit(
        session,
        "document.attach",
        username=user.username,
        investigation_id=inv.id,
        details={"entity_id": entity.id, "filename": name},
    )
    request.session["flash"] = {"level": "ok", "message": f"Metadados extraídos de {name}."}
    return RedirectResponse(f"/app/casos/{investigation_id}/entidades/{entity.id}", status_code=303)


@router.post("/app/casos/{investigation_id}/hosts-import")
async def import_host_intel(
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
    name = arquivo.filename or "hosts.json"
    if not name.lower().endswith(".json"):
        request.session["flash"] = {"level": "error", "message": "Envie um JSON de hosts já coletados."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    data = await arquivo.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        request.session["flash"] = {"level": "error", "message": "JSON acima de 8 MB."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity, FoundEvidence
    from osint4all.graph.resolve import apply_result
    from osint4all.identifiers import canonical_key
    from osint4all.intel.hosts import parse_imported_host_rows

    try:
        text = data.decode("utf-8")
    except UnicodeError:
        request.session["flash"] = {"level": "error", "message": "JSON inválido."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    rows = parse_imported_host_rows(text)
    if not rows:
        request.session["flash"] = {
            "level": "error",
            "message": "Nenhum hostname público no arquivo. Linhas só com IP de varredura são ignoradas.",
        }
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    origin = next((e for e in inv.entities if e.is_seed), None) or (inv.entities[0] if inv.entities else None)
    if origin is None:
        request.session["flash"] = {"level": "error", "message": "O caso precisa de uma semente antes de importar hosts."}
        return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)
    result = ConnectorResult()
    for obs in rows:
        url = f"https://{obs.host}"
        found = FoundEntity(
            entity_type="PROFILE",
            kind="URL",
            value=url,
            display_name=obs.host,
            attrs={"host": obs.host, "fonte": "import", "origin": "import"},
            confidence=0.4,
        )
        result.entities.append(found)
        ref = canonical_key("URL", url)
        result.edges.append(FoundEdge(from_ref=origin.canonical_key, to_ref=ref, rel_type="MENCAO", confidence=0.4, attrs={"fonte": "import"}))
        result.evidence.append(
            FoundEvidence(
                source_label="Host importado",
                url=url,
                snippet=obs.snippet or obs.host,
                payload={
                    "host": obs.host,
                    "ip": obs.ip,
                    "port": obs.port,
                    "status": obs.status,
                    "title": obs.title,
                    "tech": obs.tech,
                    "origin": "import",
                    "fonte": obs.source or "import",
                },
                entity_ref=ref,
            )
        )
    apply_result(session, inv, origin, result, connector="host_import", depth=origin.depth or 0, enqueue_children=False, max_attempts=1)
    write_audit(
        session,
        "host.import",
        username=user.username,
        investigation_id=inv.id,
        details={"filename": name, "hosts": len(rows)},
    )
    session.commit()
    request.session["flash"] = {"level": "ok", "message": f"{len(rows)} host(s) indexados no caso. Sem scan."}
    return RedirectResponse(f"/app/casos/{investigation_id}", status_code=303)


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
    if not inv:
        _set_flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    inv.monitor = not inv.monitor
    write_audit(
        session,
        "investigation.monitor",
        username=user.username,
        investigation_id=inv.id,
        details={"monitor": inv.monitor},
    )
    _set_flash(request, "ok", "Monitoramento ligado." if inv.monitor else "Monitoramento desligado.")
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
    if purge_investigation(session, investigation_id):
        write_audit(session, "investigation.purge", username=user.username, investigation_id=investigation_id)
        session.commit()
        upload = project_root() / "data" / "uploads" / investigation_id
        if upload.exists():
            import shutil

            shutil.rmtree(upload, ignore_errors=True)
        if request.session.get("current_case_id") == investigation_id:
            request.session.pop("current_case_id", None)
        request.session["flash"] = {
            "level": "ok",
            "message": "Caso apagado. Nós, vínculos, notas e uploads foram removidos.",
        }
    else:
        request.session["flash"] = {"level": "error", "message": "Esse caso já não existe."}
    return RedirectResponse("/app/casos", status_code=303)


@router.get("/app/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    audits = session.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(40)).all()
    jobs = session.scalars(select(ExpansionJob).order_by(desc(ExpansionJob.created_at)).limit(30)).all()
    health = connector_health()
    from osint4all.quality.health import latest_health

    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "admin",
            "health": health,
            "sources": source_cards(health_rows=health),
            "oss_tools": oss_cards(),
            "audits": audits,
            "jobs": jobs,
            "source_health": latest_health(session),
        }
    )
    return templates.TemplateResponse(request, "app/admin.html", ctx)


@router.post("/app/admin/saude")
def probe_source_health(
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    from osint4all.quality.health import probe_sources

    rows = probe_sources(session)
    write_audit(session, "source.health", username=user.username, details={"n": len(rows)})
    session.commit()
    failed = sum(1 for row in rows if not row.ok)
    _set_flash(request, "ok" if not failed else "error", f"Saúde das fontes: {len(rows) - failed} ok, {failed} com alerta.")
    return RedirectResponse("/app/admin", status_code=303)


@router.get("/app/manual", response_class=HTMLResponse)
def manual_page(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> HTMLResponse:
    ctx = template_context(request, user)
    ctx.update({"nav": "manual"})
    _with_cases(ctx, request, session)
    return templates.TemplateResponse(request, "app/manual.html", ctx)


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
