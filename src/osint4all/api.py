"""Aplicação FastAPI."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from osint4all.config import get_settings
from osint4all.logging_setup import get_logger
from osint4all.paths import project_root
from osint4all.db.session import init_db, session_scope
from osint4all.web.auth import seed_admin_user
from osint4all.web.router import router

logger = get_logger(__name__)
_DB_READY = True
_DB_ERROR = ""


def _warn_production_secrets() -> None:
    settings = get_settings()
    if not settings.is_production:
        return
    if settings.ui_session_secret in {"", "change-me-ui-session-secret"}:
        logger.warning("UI_SESSION_SECRET ainda é o valor padrão — troque no Railway.")
    if not (settings.ui_admin_user and settings.ui_admin_password):
        logger.warning("UI_ADMIN_USER / UI_ADMIN_PASSWORD vazios — o login pode falhar.")

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
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        if exc.status_code == 403:
            request.session["flash"] = {"level": "error", "message": "Esta ação é só para administrador."}
            return RedirectResponse("/app", status_code=303)
        return _plain(exc)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "osint4all"}

    @app.get("/ready")
    def ready() -> dict:
        from sqlalchemy import text

        if not _DB_READY:
            raise HTTPException(status_code=503, detail=_DB_ERROR or "database not ready")
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return {"ok": True, "service": "osint4all"}

    @app.get("/metrics")
    def metrics() -> dict:
        return {"ok": True, "service": "osint4all"}

    @app.on_event("startup")
    def _startup() -> None:
        global _DB_READY, _DB_ERROR
        _warn_production_secrets()
        try:
            init_db()
            with session_scope() as session:
                seed_admin_user(session)
            _DB_READY = True
            _DB_ERROR = ""
        except Exception as exc:  # noqa: BLE001
            _DB_READY = False
            _DB_ERROR = str(exc)
            logger.exception("startup_db_failed %s", exc)

    return app


def _plain(exc: HTTPException):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


app = create_app()
