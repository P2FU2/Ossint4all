"""Rotas HTML do painel Monitor Judicial."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from monitor_jus.config import get_settings
from monitor_jus.db.models import User
from monitor_jus.db.session import session_scope
from monitor_jus.models import RunType
from monitor_jus.web.auth import (
    SESSION_USER_KEY,
    authenticate_user,
    check_login_rate_limit,
    clear_login_failures,
    ensure_csrf,
    record_login_failure,
    write_audit,
)
from monitor_jus.web.deps import (
    client_ip,
    render,
    require_admin,
    require_csrf,
    require_user,
)
from monitor_jus.web.services import actions as action_svc
from monitor_jus.web.services import criteria as criteria_svc
from monitor_jus.web.services import dashboard as dashboard_svc
from monitor_jus.web.services import events as events_svc
from monitor_jus.web.services import history as history_svc
from monitor_jus.web.services import processes as processes_svc
from monitor_jus.web.services import progress_board as progress_svc
from monitor_jus.web.services import status as status_svc
from monitor_jus.web.services import system as system_svc

router = APIRouter(tags=["ui"])


def _flash(request: Request, message: str, level: str = "ok") -> None:
    request.session["flash"] = {"message": message, "level": level}


def _pop_flash(request: Request) -> dict | None:
    return request.session.pop("flash", None)


@router.get("/", response_model=None)
def root(request: Request):
    if request.session.get(SESSION_USER_KEY):
        return RedirectResponse(url="/app", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login", response_model=None)
def login_page(request: Request):
    if request.session.get(SESSION_USER_KEY):
        return RedirectResponse(url="/app", status_code=303)
    ensure_csrf(request.session)
    return render(request, "app/login.html", error=request.query_params.get("error"))


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    ip = client_ip(request)
    if not check_login_rate_limit(ip):
        return RedirectResponse(url="/login?error=rate", status_code=303)

    with session_scope() as session:
        user = authenticate_user(session, username, password)
        if not user:
            record_login_failure(ip)
            write_audit(session, "auth.login_failed", username=username, details={"ip": ip})
            return RedirectResponse(url="/login?error=creds", status_code=303)
        clear_login_failures(ip)
        request.session[SESSION_USER_KEY] = user.id
        ensure_csrf(request.session)
        write_audit(session, "auth.login", username=user.username, details={"ip": ip})
    return RedirectResponse(url="/app", status_code=303)


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    with session_scope() as session:
        write_audit(session, "auth.logout", username=user.username)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/app", response_model=None)
def app_dashboard(request: Request, user: User = Depends(require_user)):
    settings = get_settings()
    with session_scope() as session:
        data = dashboard_svc.build_dashboard(session, settings, user=user)
    return render(
        request,
        "app/dashboard.html",
        user,
        flash=_pop_flash(request),
        **data,
        nav="dashboard",
        nav_group="consulta",
    )


@router.get("/app/acompanhamento", response_model=None)
def app_acompanhamento(request: Request, user: User = Depends(require_admin)):
    settings = get_settings()
    with session_scope() as session:
        cleaned = action_svc.cleanup_stale_jobs(session)
        data = progress_svc.build_progress_board(session)
        data["cleaned"] = cleaned
    return render(
        request,
        "app/acompanhamento.html",
        user,
        flash=_pop_flash(request),
        **data,
        default_email_to=settings.email_to or "",
        nav="acompanhamento",
        nav_group="admin",
    )


@router.get("/app/acompanhamento/partial", response_model=None)
def app_acompanhamento_partial(request: Request, user: User = Depends(require_admin)):
    settings = get_settings()
    with session_scope() as session:
        cleaned = action_svc.cleanup_stale_jobs(session)
        data = progress_svc.build_progress_board(session)
        data["cleaned"] = cleaned
    return render(
        request,
        "app/partials/acompanhamento_body.html",
        user,
        **data,
        default_email_to=settings.email_to or "",
        nav="acompanhamento",
        nav_group="admin",
    )


@router.get("/app/status", response_model=None)
def app_status(request: Request, user: User = Depends(require_admin)):
    settings = get_settings()
    with session_scope() as session:
        action_svc.cleanup_stale_jobs(session)
        data = status_svc.build_pipeline_status(session, settings)
    return render(
        request,
        "app/status.html",
        user,
        flash=_pop_flash(request),
        **data,
        nav="status",
        nav_group="admin",
    )


@router.get("/app/status/partial", response_model=None)
def app_status_partial(request: Request, user: User = Depends(require_admin)):
    settings = get_settings()
    with session_scope() as session:
        data = status_svc.build_pipeline_status(session, settings)
    return render(
        request,
        "app/partials/status_body.html",
        user,
        **data,
        nav="status",
        nav_group="admin",
    )


@router.get("/app/processos", response_model=None)
def app_processes(
    request: Request,
    user: User = Depends(require_user),
    q: str = Query(""),
    tribunal: str = Query(""),
    oab: str = Query(""),
    outcome: str = Query(""),
    situacao: str = Query(""),
    pending_only: bool = Query(False),
    sort_by: str = Query("last_movement_at"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
):
    with session_scope() as session:
        data = processes_svc.list_processes(
            session,
            q=q,
            tribunal=tribunal,
            oab=oab,
            outcome=outcome,
            situacao=situacao,
            pending_only=pending_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )
    return render(
        request,
        "app/processes.html",
        user,
        flash=_pop_flash(request),
        **data,
        nav="processos",
        nav_group="consulta",
    )


@router.get("/app/processos/export.csv")
def app_processes_csv(
    request: Request,
    user: User = Depends(require_user),
    q: str = Query(""),
    tribunal: str = Query(""),
    oab: str = Query(""),
    outcome: str = Query(""),
    situacao: str = Query(""),
    pending_only: bool = Query(False),
    sort_by: str = Query("last_movement_at"),
    sort_dir: str = Query("desc"),
) -> Response:
    with session_scope() as session:
        content = processes_svc.processes_csv(
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
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=acervo_processos.csv"},
    )


@router.get("/app/processos/{process_id}", response_model=None)
def app_process_detail(request: Request, process_id: str, user: User = Depends(require_user)):
    with session_scope() as session:
        data = processes_svc.get_process_detail(session, process_id)
    if not data:
        raise StarletteHTTPException(status_code=404, detail="Processo não encontrado")
    return render(
        request,
        "app/process_detail.html",
        user,
        process=data,
        nav="processos",
        nav_group="consulta",
    )


@router.get("/app/eventos", response_model=None)
def app_events(
    request: Request,
    user: User = Depends(require_user),
    notify_status: str = Query(""),
    priority: str = Query(""),
    event_type: str = Query(""),
    q: str = Query(""),
    deadline_only: bool = Query(False),
):
    with session_scope() as session:
        data = events_svc.list_events(
            session,
            notify_status=notify_status,
            priority=priority,
            event_type=event_type,
            q=q,
            deadline_only=deadline_only,
        )
    return render(
        request,
        "app/events.html",
        user,
        flash=_pop_flash(request),
        **data,
        nav="eventos",
        nav_group="consulta",
    )


@router.get("/app/eventos/{event_id}", response_model=None)
def app_event_detail(request: Request, event_id: str, user: User = Depends(require_user)):
    with session_scope() as session:
        data = events_svc.get_event_detail(session, event_id)
    if not data:
        raise StarletteHTTPException(status_code=404, detail="Evento não encontrado")
    return render(
        request,
        "app/event_detail.html",
        user,
        event=data,
        nav="eventos",
        nav_group="consulta",
    )


@router.get("/app/historico", response_model=None)
def app_history(request: Request, user: User = Depends(require_user)):
    settings = get_settings()
    with session_scope() as session:
        data = history_svc.list_digests(session)
    return render(
        request,
        "app/history.html",
        user,
        flash=_pop_flash(request),
        **data,
        default_email_to=settings.email_to or "",
        nav="historico",
        nav_group="consulta",
    )


@router.get("/app/historico/{digest_id}", response_model=None)
def app_history_detail(request: Request, digest_id: str, user: User = Depends(require_user)):
    settings = get_settings()
    with session_scope() as session:
        data = history_svc.get_digest_detail(session, digest_id, settings)
    if not data:
        raise StarletteHTTPException(status_code=404, detail="Digest não encontrado")
    return render(
        request,
        "app/history_detail.html",
        user,
        flash=_pop_flash(request),
        digest=data,
        nav="historico",
        nav_group="consulta",
    )


@router.get("/app/historico/{digest_id}/html")
def app_history_html(request: Request, digest_id: str, user: User = Depends(require_user)):
    settings = get_settings()
    with session_scope() as session:
        data = history_svc.get_digest_detail(session, digest_id, settings)
    if not data or not data.get("html_exists"):
        raise StarletteHTTPException(status_code=404, detail="HTML do digest indisponível")
    path = Path(data["html_path"])
    return FileResponse(path, media_type="text/html")


@router.get("/app/historico/{digest_id}/pdf")
def app_history_pdf(request: Request, digest_id: str, user: User = Depends(require_user)):
    settings = get_settings()
    with session_scope() as session:
        data = history_svc.get_digest_detail(session, digest_id, settings)
    if not data or not data.get("pdf_exists"):
        raise StarletteHTTPException(status_code=404, detail="PDF do digest indisponível")
    path = Path(data["pdf_path"])
    filename = f"monitor-judicial-{data.get('reference_date') or digest_id[:8]}.pdf"
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/app/criterios", response_model=None)
def app_criteria(request: Request, user: User = Depends(require_admin)):
    settings = get_settings()
    with session_scope() as session:
        data = criteria_svc.list_criteria(session, settings)
    return render(
        request,
        "app/criteria.html",
        user,
        flash=_pop_flash(request),
        **data,
        nav="criterios",
        nav_group="admin",
    )


@router.get("/app/sistema", response_model=None)
def app_system(request: Request, user: User = Depends(require_admin)):
    settings = get_settings()
    with session_scope() as session:
        data = system_svc.build_system_view(session, settings)
    return render(
        request,
        "app/system.html",
        user,
        flash=_pop_flash(request),
        **data,
        nav="sistema",
        nav_group="admin",
    )


@router.post("/app/actions/ops-config")
async def app_ops_config(
    request: Request,
    user: User = Depends(require_admin),
) -> RedirectResponse:
    """Salva config/ops.yaml a partir do formulário Disparar."""
    from monitor_jus.ops_config import save_ops

    form = await request.form()
    require_csrf(request, str(form.get("csrf_token") or ""))
    data = {
        "discovery": {
            "lookback_days": form.get("discovery_lookback_days"),
            "max_pages": form.get("discovery_max_pages"),
            "search_oabs": "search_oabs" in form,
            "search_names": "search_names" in form,
            "search_processes": "search_processes" in form,
            "search_companies": "search_companies" in form,
        },
        "bootstrap": {
            "lookback_days": form.get("bootstrap_lookback_days"),
            "max_pages": form.get("bootstrap_max_pages"),
            "complete_missing_capa": "complete_missing_capa" in form,
            "ignore_events_for_digest": "ignore_events_for_digest" in form,
        },
    }
    try:
        path = save_ops(data)
        _flash(request, f"Configuração salva em {path}", "ok")
    except Exception as exc:  # noqa: BLE001
        _flash(request, f"Falha ao salvar ops: {exc}", "error")
    return RedirectResponse(url="/app/acompanhamento", status_code=303)


@router.post("/app/actions/enqueue")
def app_enqueue(
    request: Request,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
    run_type: str = Form(...),
    digest_id: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    settings = get_settings()
    payload = {}
    if run_type == RunType.DELIVERY_RETRY.value and digest_id:
        payload["digest_id"] = digest_id
    try:
        with session_scope() as session:
            result = action_svc.enqueue_from_ui(
                session,
                settings,
                run_type=run_type,
                username=user.username,
                payload=payload,
            )
        _flash(request, f"Job enfileirado: {run_type} · run {result['run_id'][:8]}…", "ok")
    except ValueError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(url="/app/acompanhamento", status_code=303)


def _safe_app_path(raw: str, default: str) -> str:
    path = (raw or "").strip() or default
    return path if path.startswith("/app/") else default


@router.post("/app/actions/cancel-run")
def app_cancel_run(
    request: Request,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
    run_id: str = Form(...),
    next_path: str = Form("/app/status"),
) -> RedirectResponse:
    redirect_to = _safe_app_path(next_path, "/app/status")
    from monitor_jus.web.auth import validate_csrf

    token = csrf_token or request.headers.get("x-csrf-token")
    if not validate_csrf(request.session, token):
        _flash(request, "CSRF inválido — recarregue a página e tente cancelar de novo", "error")
        return RedirectResponse(url=redirect_to, status_code=303)
    try:
        with session_scope() as session:
            result = action_svc.cancel_run(
                session, run_id=run_id, username=user.username
            )
        _flash(
            request,
            f"Run {result['run_type']} cancelado · {result['jobs_cancelled']} job(s)",
            "ok",
        )
    except ValueError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(url=redirect_to, status_code=303)


@router.post("/app/actions/cancel-job")
def app_cancel_job(
    request: Request,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
    job_id: str = Form(...),
    next_path: str = Form("/app/acompanhamento"),
) -> RedirectResponse:
    redirect_to = _safe_app_path(next_path, "/app/acompanhamento")
    from monitor_jus.web.auth import validate_csrf

    token = csrf_token or request.headers.get("x-csrf-token")
    if not validate_csrf(request.session, token):
        _flash(request, "CSRF inválido — recarregue a página e tente cancelar de novo", "error")
        return RedirectResponse(url=redirect_to, status_code=303)
    try:
        with session_scope() as session:
            result = action_svc.cancel_job(
                session, job_id=job_id, username=user.username
            )
        _flash(request, f"Job {result['job_type']} cancelado", "ok")
    except ValueError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(url=redirect_to, status_code=303)


@router.post("/app/actions/send-report")
def app_send_report(
    request: Request,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
    email_to: str = Form(...),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    settings = get_settings()
    try:
        with session_scope() as session:
            result = action_svc.enqueue_report_email(
                session,
                settings,
                username=user.username,
                email_to=email_to,
            )
        _flash(
            request,
            f"Relatório enfileirado para {email_to.strip()} · run {result['run_id'][:8]}…",
            "ok",
        )
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse(url="/app", status_code=303)
    return RedirectResponse(url="/app/acompanhamento", status_code=303)


@router.post("/app/actions/sync-criteria")
def app_sync_criteria(
    request: Request,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    settings = get_settings()
    try:
        with session_scope() as session:
            result = criteria_svc.sync_criteria(session, settings)
            write_audit(
                session,
                "criteria.sync",
                username=user.username,
                details=result,
            )
        oabs = ", ".join(result.get("yaml_oabs") or []) or "—"
        msg = (
            f"YAML sync: {result.get('changes', 0)} alteração(ões) · "
            f"OABs no arquivo: {oabs}"
        )
        if result.get("backfill_error"):
            msg += " · aviso: backfill de vínculos falhou (critérios já salvos)"
            _flash(request, msg, "warn")
        else:
            bf = result.get("oab_links_backfilled") or 0
            if bf:
                msg += f" · {bf} vínculo(s) OAB"
            _flash(request, msg, "ok")
    except Exception as exc:  # noqa: BLE001
        _flash(request, f"Falha ao sincronizar YAML: {exc}", "error")
    return RedirectResponse(url="/app/criterios", status_code=303)


@router.post("/app/actions/users/create")
def app_create_user(
    request: Request,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("viewer"),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    try:
        with session_scope() as session:
            system_svc.create_user(
                session,
                username=username,
                password=password,
                role=role,
                actor=user.username,
            )
        _flash(request, f"Usuário {username} criado", "ok")
    except ValueError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(url="/app/sistema", status_code=303)


@router.post("/app/actions/users/{user_id}/toggle")
def app_toggle_user(
    request: Request,
    user_id: str,
    user: User = Depends(require_admin),
    csrf_token: str = Form(""),
    active: str = Form("0"),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    try:
        with session_scope() as session:
            system_svc.set_user_active(session, user_id, active == "1", user.username)
        _flash(request, "Usuário atualizado", "ok")
    except ValueError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(url="/app/sistema", status_code=303)
