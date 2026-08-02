"""Ações administrativas do painel (enqueue)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from monitor_jus.config import Settings
from monitor_jus.db.repository import Repository
from monitor_jus.models import RunMode, RunType
from monitor_jus.web.auth import write_audit

ALLOWED_RUN_TYPES = {
    RunType.DAILY_DIGEST.value,
    RunType.BOOTSTRAP.value,
    RunType.HISTORICAL_DISCOVERY.value,
    RunType.RECONCILIATION.value,
    RunType.DELIVERY_RETRY.value,
    RunType.PROCESS_REFRESH.value,
}


def enqueue_from_ui(
    session: Session,
    settings: Settings,
    *,
    run_type: str,
    username: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    if run_type not in ALLOWED_RUN_TYPES:
        raise ValueError(f"run_type não permitido: {run_type}")

    repo = Repository(session)
    idem = f"ui:{run_type}:{uuid4().hex[:12]}"
    run = repo.create_run(
        run_type,
        trigger_type="ui",
        run_mode=RunMode.LIVE.value,
        idempotency_key=idem,
    )
    job_type = run_type
    if run_type == RunType.BOOTSTRAP.value:
        job_type = "BOOTSTRAP"
    repo.enqueue_job(
        run.id,
        job_type,
        payload=payload or {},
        max_attempts=settings.job_max_attempts,
        idempotency_key=f"job:{idem}",
    )
    write_audit(
        session,
        "run.enqueue",
        username=username,
        details={"run_type": run_type, "run_id": run.id, "payload": payload or {}},
    )
    return {"run_id": run.id, "status": "accepted"}
