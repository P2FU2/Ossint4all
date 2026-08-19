"""Aplicação FastAPI."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from osint4all.config import get_settings
from osint4all.exceptions import ConfigurationError
from osint4all.paths import project_root
from osint4all.db.session import init_db, session_scope
from osint4all.web.auth import seed_admin_user
from osint4all.web.router import router


def _assert_production_secrets() -> None:
    settings = get_settings()
    if not settings.is_production:
        return
    if settings.ui_session_secret in {"", "change-me-ui-session-secret"}:
        raise ConfigurationError("Defina UI_SESSION_SECRET no Railway (produção).")
    if not (settings.ui_admin_user and settings.ui_admin_password):
        raise ConfigurationError("Defina UI_ADMIN_USER e UI_ADMIN_PASSWORD no Railway.")

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="OSINT4ALL", docs_url=None, redoc_url=None)
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.ui_session_secret,
        session_cookie="osint4all_session",
        max_age=settings.ui_session_hours * 3600,
        same_site="lax",
        https_only=settings.is_production,
    )
    app.include_router(router)
    static_dir = project_root() / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        if exc.status_code in {303, 302} and exc.headers and exc.headers.get("Location"):
            return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
        if exc.status_code == 303:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/login", status_code=303) if exc.status_code in {401, 403} and not request.url.path.startswith("/app/admin") else _plain(exc)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "osint4all"}

    @app.on_event("startup")
    def _startup() -> None:
        _assert_production_secrets()
        init_db()
        with session_scope() as session:
            seed_admin_user(session)

    return app


def _plain(exc: HTTPException):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


app = create_app()
