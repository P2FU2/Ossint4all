"""Worker que consome jobs da fila."""

from __future__ import annotations

import socket
import time
import traceback
from typing import Any
from uuid import uuid4

from monitor_jus.config import get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.exceptions import PermanentJobError, RecoverableJobError, SourceOutcomeError
from monitor_jus.logging_setup import get_logger, setup_logging
from monitor_jus.metrics import incr
from monitor_jus.models import JobStatus, JobType, RunStatus
from monitor_jus.pipeline.bootstrap import run_bootstrap, sync_criteria_from_config
from monitor_jus.pipeline.digest import build_and_send_digest
from monitor_jus.pipeline.discovery import run_discovery
from monitor_jus.pipeline.tracking import run_tracking
from monitor_jus.pipeline.webhook_ingest import ingest_webhook_raw

logger = get_logger(__name__)


def process_job(job_id: str) -> None:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session)
        from monitor_jus.db.models import Job

        job = session.get(Job, job_id)
        if not job:
            return
        try:
            result = _dispatch(session, job.job_type, job.payload or {}, job.run_id)
            repo.complete_job(job)
            if job.run_id:
                # se todos jobs do run terminaram, marca success
                from sqlalchemy import select
                from monitor_jus.db.models import Job as JobModel

                pending = session.scalars(
                    select(JobModel).where(
                        JobModel.run_id == job.run_id,
                        JobModel.status.in_(
                            [
                                JobStatus.PENDING.value,
                                JobStatus.RUNNING.value,
                                JobStatus.RETRY.value,
                            ]
                        ),
                        JobModel.id != job.id,
                    )
                ).first()
                if not pending:
                    repo.finish_run(job.run_id, RunStatus.SUCCESS.value)
            logger.info("job_success", extra={"job_id": job.id, "extra": result})
        except RecoverableJobError as exc:
            incr("jobs_failed")
            repo.fail_job(
                job,
                error_code=exc.code,
                error_message=exc.message or str(exc),
                recoverable=True,
            )
        except (PermanentJobError, SourceOutcomeError) as exc:
            incr("jobs_failed")
            code = getattr(exc, "code", "PERMANENT")
            recoverable = False
            if isinstance(exc, SourceOutcomeError) and exc.code.startswith("FAILED_"):
                recoverable = True
            repo.fail_job(
                job,
                error_code=code,
                error_message=str(exc),
                recoverable=recoverable,
            )
            if job.status == JobStatus.DEAD.value:
                incr("jobs_dead")
        except Exception as exc:  # noqa: BLE001
            incr("jobs_failed")
            repo.fail_job(
                job,
                error_code="UNHANDLED",
                error_message=f"{exc}\n{traceback.format_exc()}",
                recoverable=True,
            )


def _dispatch(session, job_type: str, payload: dict[str, Any], run_id: str | None) -> dict[str, Any]:
    settings = get_settings()
    if job_type == JobType.WEBHOOK_INGEST.value:
        return ingest_webhook_raw(session, payload["webhook_id"], settings)
    if job_type == JobType.HISTORICAL_DISCOVERY.value:
        sync_criteria_from_config(session, settings)
        return run_discovery(session, settings=settings, bootstrap_mode=False)
    if job_type == JobType.DAILY_DIGEST.value:
        return build_and_send_digest(session, run_id=run_id, settings=settings)
    if job_type == JobType.DELIVERY_RETRY.value:
        return build_and_send_digest(
            session,
            run_id=run_id,
            settings=settings,
            digest_id=payload.get("digest_id"),
        )
    if job_type == JobType.PROCESS_REFRESH.value:
        return run_tracking(session, settings=settings)
    if job_type == JobType.RECONCILIATION.value:
        return run_tracking(session, settings=settings)
    if job_type == "BOOTSTRAP":
        sync_criteria_from_config(session, settings)
        return run_bootstrap(session, settings)
    # subjobs do digest podem ser tratados de forma monolítica na v1
    if job_type in (
        JobType.LOAD_PENDING_EVENTS.value,
        JobType.GENERATE_SUMMARIES.value,
        JobType.BUILD_HTML.value,
        JobType.SEND_EMAIL.value,
    ):
        return build_and_send_digest(session, run_id=run_id, settings=settings)
    raise PermanentJobError(f"job_type desconhecido: {job_type}")


def worker_loop(poll_seconds: float = 2.0) -> None:
    settings = get_settings()
    setup_logging()
    init_db()
    worker_id = f"{socket.gethostname()}-{uuid4().hex[:8]}"
    logger.info("worker_started", extra={"extra": {"worker_id": worker_id}})
    while True:
        claimed = None
        with session_scope() as session:
            repo = Repository(session)
            pending = repo.count_jobs_by_status(JobStatus.PENDING.value)
            incr("jobs_pending", 0)  # emit snapshot via gauge-like log
            from monitor_jus.metrics import set_gauge

            set_gauge("jobs_pending", float(pending))
            job = repo.claim_next_job(worker_id)
            if job:
                claimed = job.id
        if claimed:
            process_job(claimed)
        else:
            time.sleep(poll_seconds)


def main() -> None:
    worker_loop()


if __name__ == "__main__":
    main()
