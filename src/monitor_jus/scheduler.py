"""Scheduler — apenas enfileira jobs conforme cron."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from monitor_jus.config import get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.logging_setup import get_logger, setup_logging
from monitor_jus.models import JobType, RunMode, RunType

logger = get_logger(__name__)


def _cron_expr() -> str:
    settings = get_settings()
    if settings.schedule_cron:
        return settings.schedule_cron
    return f"0 {settings.schedule_hour} * * *"


def enqueue_daily_digest() -> str:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session)
        day = datetime.now(ZoneInfo(settings.tz)).date().isoformat()
        run = repo.create_run(
            RunType.DAILY_DIGEST.value,
            trigger_type="schedule",
            run_mode=RunMode.LIVE.value,
            idempotency_key=f"digest:{day}",
        )
        job = repo.enqueue_job(
            run.id,
            JobType.DAILY_DIGEST.value,
            payload={},
            max_attempts=settings.job_max_attempts,
            idempotency_key=f"digest-job:{day}",
        )
        return job.id


def enqueue_refresh() -> str:
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session)
        run = repo.create_run(
            RunType.PROCESS_REFRESH.value,
            trigger_type="schedule",
            run_mode=RunMode.LIVE.value,
        )
        job = repo.enqueue_job(
            run.id,
            JobType.PROCESS_REFRESH.value,
            max_attempts=settings.job_max_attempts,
        )
        return job.id


def scheduler_loop() -> None:
    setup_logging()
    init_db()
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    expr = _cron_expr()
    logger.info("scheduler_started", extra={"extra": {"cron": expr, "tz": settings.tz}})
    base = datetime.now(tz)
    cron = croniter(expr, base)
    next_run = cron.get_next(datetime)
    while True:
        now = datetime.now(tz)
        if now >= next_run:
            try:
                job_id = enqueue_daily_digest()
                logger.info("digest_enqueued", extra={"job_id": job_id})
            except Exception as exc:  # noqa: BLE001
                logger.error("schedule_enqueue_failed", extra={"extra": {"err": str(exc)}})
            next_run = cron.get_next(datetime)
        time.sleep(20)


def main() -> None:
    scheduler_loop()


if __name__ == "__main__":
    main()
