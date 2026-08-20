"""Dependências FastAPI do painel."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from osint4all.config import get_settings
from osint4all.db.models import User
from osint4all.db.session import get_session_factory
from osint4all.web.auth import SESSION_USER_KEY, ensure_csrf, get_user_by_id, validate_csrf


def db_session() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(request: Request, session: Session = Depends(db_session)) -> User:
    uid = request.session.get(SESSION_USER_KEY)
    user = get_user_by_id(session, str(uid)) if uid else None
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="somente admin")
    return user


def template_context(request: Request, user: User | None = None) -> dict:
    return {
        "request": request,
        "user": user,
        "is_admin": bool(user and user.role == "admin"),
        "csrf_token": ensure_csrf(request.session),
        "brand": "OSINT4ALL",
        "app_name": "Consultar",
        "flash": request.session.pop("flash", None),
        "current_case_id": request.session.get("current_case_id"),
    }


def require_csrf(request: Request, token: str | None) -> None:
    if validate_csrf(request.session, token):
        return
    request.session["flash"] = {
        "level": "error",
        "message": "Sessão expirada. Recarregue a página e tente de novo.",
    }
    referer = request.headers.get("referer") or ""
    location = "/app"
    if referer.startswith("/") and not referer.startswith("//"):
        location = referer
    elif referer.startswith(str(request.base_url)):
        location = referer
    raise HTTPException(status_code=303, headers={"Location": location})


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def settings_dep():
    return get_settings()
