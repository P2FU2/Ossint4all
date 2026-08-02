"""Handlers HTTP do painel."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_ui_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Dependências do painel usam 303 + Location para forçar login
        if exc.status_code in (303, 307) and exc.headers and "Location" in exc.headers:
            return RedirectResponse(url=exc.headers["Location"], status_code=exc.status_code)
        path = request.url.path
        accept = request.headers.get("accept", "")
        wants_html = "text/html" in accept
        ui_path = path.startswith("/app") or path in ("/login", "/logout", "/")
        if (
            exc.status_code in (401, 403)
            and ui_path
            and wants_html
        ):
            return RedirectResponse(url="/login", status_code=303)
        if wants_html and ui_path and exc.status_code >= 400:
            from monitor_jus.web.deps import render

            return render(
                request,
                "app/error.html",
                status_code=exc.status_code,
                detail=str(exc.detail),
                error_code=exc.status_code,
            )
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
