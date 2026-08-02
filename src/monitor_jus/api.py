"""API FastAPI — health, run, webhooks, metrics + painel web."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from monitor_jus import NORMALIZER_VERSION, PROVIDER_SCHEMA_VERSION_JUDIT, __version__
from monitor_jus.ai.summarizer import check_openrouter
from monitor_jus.capabilities import sync_capabilities
from monitor_jus.config import Settings, get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import get_engine, init_db, session_scope
from monitor_jus.exceptions import ConfigurationError, WebhookAuthError
from monitor_jus.logging_setup import get_logger, setup_logging
from monitor_jus.metrics import incr, snapshot
from monitor_jus.models import JobType, RunMode, RunType
from monitor_jus.sources.judit.auth import build_webhook_authenticator
from monitor_jus.sources.judit.webhooks import webhook_meta
from monitor_jus.web.auth import seed_admin_user
from monitor_jus.web.exception_handlers import register_ui_exception_handlers
from monitor_jus.web.router import router as ui_router

logger = get_logger(__name__)

app = FastAPI(title="Monitor Judicial", version=__version__)

_settings_boot = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=_settings_boot.ui_session_secret,
    session_cookie="monitor_jus_session",
    max_age=max(3600, int(_settings_boot.ui_session_hours) * 3600),
    same_site="lax",
    https_only=_settings_boot.is_production,
)
register_ui_exception_handlers(app)

class _CachedStaticFiles(StaticFiles):
    """Static com cache longo (CSS/JS do painel)."""

    def file_response(self, full_path, stat_result, scope, status_code: int = 200):  # type: ignore[no-untyped-def]
        resp = super().file_response(full_path, stat_result, scope, status_code)
        resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
        return resp


_static_dir = Path("static")
if _static_dir.is_dir():
    app.mount("/static", _CachedStaticFiles(directory=str(_static_dir)), name="static")

app.include_router(ui_router)


class EnqueueBody(BaseModel):
    run_type: str = RunType.DAILY_DIGEST.value
    run_mode: str = RunMode.LIVE.value
    payload: dict[str, Any] = Field(default_factory=dict)


def verify_trigger_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token obrigatório")
    token = authorization.split(" ", 1)[1].strip()
    if token != settings.api_trigger_token:
        raise HTTPException(status_code=403, detail="Token inválido")


@app.on_event("startup")
def on_startup() -> None:
    setup_logging()
    settings = get_settings()
    if settings.is_production and settings.judit_webhook_auth_mode == "none":
        raise ConfigurationError("Webhook auth none proibido em produção")
    if settings.is_production and (
        not settings.ui_session_secret or settings.ui_session_secret == "change-me-ui-session-secret"
    ):
        raise ConfigurationError("UI_SESSION_SECRET deve ser definido em produção")
    init_db()
    with session_scope() as session:
        sync_capabilities(session, settings)
        seed_admin_user(session, settings)
    check_openrouter(settings)
    logger.info("api_started", extra={"extra": {"version": __version__}})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/metrics")
def metrics(_: None = Depends(verify_trigger_token)) -> dict[str, Any]:
    return snapshot()


@app.post("/run", status_code=202)
def enqueue_run(
    body: EnqueueBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(verify_trigger_token),
) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as session:
        from monitor_jus.web.services.actions import (
            assert_heavy_job_allowed,
            cancel_stale_pending_jobs,
        )

        cancel_stale_pending_jobs(session, hours=2.0)
        try:
            assert_heavy_job_allowed(session, body.run_type)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        repo = Repository(session)
        run = repo.create_run(
            body.run_type,
            trigger_type="api",
            run_mode=body.run_mode,
            idempotency_key=idempotency_key,
        )
        job_type = body.run_type
        if body.run_type == RunType.BOOTSTRAP.value:
            job_type = "BOOTSTRAP"
        repo.enqueue_job(
            run.id,
            job_type,
            payload=body.payload,
            max_attempts=settings.job_max_attempts,
            idempotency_key=f"job:{idempotency_key}" if idempotency_key else None,
        )
        return {"run_id": run.id, "status": "accepted"}


@app.get("/runs/{run_id}")
def get_run(run_id: str, _: None = Depends(verify_trigger_token)) -> dict[str, Any]:
    with session_scope() as session:
        repo = Repository(session)
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run não encontrado")
        from sqlalchemy import select
        from monitor_jus.db.models import Job

        from monitor_jus.progress import job_progress_dict

        jobs = list(session.scalars(select(Job).where(Job.run_id == run_id)).all())
        return {
            "run_id": run.id,
            "run_type": run.run_type,
            "status": run.status,
            "run_mode": run.run_mode,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_summary": run.error_summary,
            "jobs": [
                {
                    "id": j.id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "attempt_count": j.attempt_count,
                    "last_error_code": j.last_error_code,
                    "last_error_message": (j.last_error_message or "")[:400] or None,
                    "heartbeat_at": j.heartbeat_at,
                    **job_progress_dict(j),
                }
                for j in jobs
            ],
        }


@app.post("/webhooks/judit")
async def judit_webhook(request: Request) -> JSONResponse:
    settings = get_settings()
    raw_body = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    try:
        auth = build_webhook_authenticator(settings)
        if not auth.validate(headers, raw_body):
            raise WebhookAuthError("assinatura/token inválido")
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WebhookAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    meta = webhook_meta(payload, headers)
    incr("webhooks_received")

    with session_scope() as session:
        repo = Repository(session)
        if repo.webhook_delivery_exists(meta["delivery_key"]):
            incr("webhooks_duplicate")
            return JSONResponse({"status": "duplicate"}, status_code=200)

        raw = repo.save_webhook(
            delivery_key=meta["delivery_key"],
            payload=payload,
            headers=headers,
            provider_schema_version=meta["provider_schema_version"]
            or PROVIDER_SCHEMA_VERSION_JUDIT,
            normalizer_version=meta["normalizer_version"] or NORMALIZER_VERSION,
            webhook_delivery_id=meta.get("webhook_delivery_id"),
        )
        run = repo.create_run(
            RunType.WEBHOOK_INGEST.value,
            trigger_type="webhook",
            run_mode=RunMode.LIVE.value,
            idempotency_key=f"wh:{meta['delivery_key']}",
        )
        repo.enqueue_job(
            run.id,
            JobType.WEBHOOK_INGEST.value,
            payload={"webhook_id": raw.id},
            max_attempts=settings.job_max_attempts,
            idempotency_key=f"ingest:{meta['delivery_key']}",
        )

    # resposta rápida
    return JSONResponse({"status": "accepted"}, status_code=200)
