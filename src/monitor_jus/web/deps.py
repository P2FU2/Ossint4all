"""Dependências FastAPI do painel."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from monitor_jus.config import get_settings
from monitor_jus.db.models import User
from monitor_jus.db.session import session_scope
from monitor_jus.pipeline.status_oficial import SITUACAO_LABELS
from monitor_jus.web.auth import (
    SESSION_USER_KEY,
    ensure_csrf,
    get_user_by_id,
    validate_csrf,
)

TEMPLATES_DIR = Path("templates")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

OUTCOME_LABELS = {
    "ativo": "Em tramitação",
    "exito": "Êxito (estimado)",
    "derrota": "Desfavorável (estimado)",
    "encerrado": "Encerrado",
    "indefinido": "Sem status claro",
}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def require_user(request: Request) -> User:
    uid = request.session.get(SESSION_USER_KEY)
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    with session_scope() as session:
        user = get_user_by_id(session, str(uid))
        if not user:
            request.session.clear()
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/login"},
            )
        session.expunge(user)
        return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return user


def require_csrf(request: Request, csrf_token: str | None) -> None:
    if not validate_csrf(request.session, csrf_token):
        raise HTTPException(status_code=400, detail="CSRF inválido — recarregue a página")


def template_context(request: Request, user: User | None = None, **extra: object) -> dict:
    """Contexto Jinja (sem `request` — passado à parte no TemplateResponse)."""
    settings = get_settings()
    csrf = ensure_csrf(request.session)
    ctx: dict = {
        "user": user,
        "csrf_token": csrf,
        "brand": "Authentic",
        "app_name": "Monitor Judicial",
        "outcome_labels": OUTCOME_LABELS,
        "situacao_labels": SITUACAO_LABELS,
        "is_admin": bool(user and user.role == "admin"),
        "tz": settings.tz,
    }
    ctx.update(extra)
    return ctx


def render(
    request: Request,
    name: str,
    user: User | None = None,
    *,
    status_code: int = 200,
    **extra: object,
):
    return templates.TemplateResponse(
        request,
        name,
        template_context(request, user, **extra),
        status_code=status_code,
    )


def redirect_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def client_ip(request: Request) -> str:
    return _client_ip(request)
