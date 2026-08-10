"""Scheduler — enfileira jobs conforme jobs.yaml + cron do digest."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

from monitor_jus.config import Settings, get_settings, load_yaml
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.logging_setup import get_logger, setup_logging
from monitor_jus.models import JobType, RunMode, RunType

logger = get_logger(__name__)


def _cron_expr(settings: Settings) -> str:
    if settings.schedule_cron:
        return settings.schedule_cron
    return f"0 {settings.schedule_hour} * * *"


def _jobs_cfg(settings: Settings) -> dict[str, Any]:
    data = load_yaml(settings.config_path("jobs.yaml"))
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def _job_enabled(cfg: dict[str, Any], key: str) -> bool:
    block = cfg.get(key) or {}
    if not isinstance(block, dict):
        return True
    return block.get("enabled", True) is not False


def _enqueue(
    repo: Repository,
    *,
    run_type: str,
    job_type: str,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> str | None:
    """Enfileira com key de janela + barreira has_active_job.

    Ordem: (1) mesma key → devolve job existente; (2) tipo já ativo → skip;
    (3) cria novo.
    """
    from sqlalchemy import select

    from monitor_jus.db.models import Job

    existing = repo.session.scalar(
        select(Job).where(Job.idempotency_key == idempotency_key)
    )
    if existing:
        return existing.id
    if repo.has_active_job(job_type):
        logger.info(
            "schedule_skip_active",
            extra={"extra": {"job_type": job_type, "key": idempotency_key}},
        )
        return None
    run = repo.create_run(
        run_type,
        trigger_type="schedule",
        run_mode=RunMode.LIVE.value,
        idempotency_key=f"run:{idempotency_key}",
    )
    job = repo.enqueue_job(
        run.id,
        job_type,
        payload=payload or {},
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )
    return job.id if job else None


def enqueue_daily_digest(*, settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    with session_scope() as session:
        repo = Repository(session)
        day = datetime.now(ZoneInfo(settings.tz)).date().isoformat()
        return _enqueue(
            repo,
            run_type=RunType.DAILY_DIGEST.value,
            job_type=JobType.DAILY_DIGEST.value,
            idempotency_key=f"digest:{day}",
            max_attempts=settings.job_max_attempts,
        )


def enqueue_djen_poll(*, settings: Settings | None = None, now: datetime | None = None) -> str | None:
    settings = settings or get_settings()
    tz = ZoneInfo(settings.tz)
    now = now or datetime.now(tz)
    slot = now.strftime("%Y-%m-%d-%H")
    with session_scope() as session:
        repo = Repository(session)
        # Evita corrida de notify com Bootstrap / Discovery histórica
        for heavy in ("BOOTSTRAP", "HISTORICAL_DISCOVERY"):
            if repo.has_active_job(heavy):
                logger.info(
                    "schedule_skip_djen_during_heavy",
                    extra={"extra": {"active": heavy, "slot": slot}},
                )
                return None
        return _enqueue(
            repo,
            run_type=RunType.DJEN_POLL.value,
            job_type=JobType.DJEN_POLL.value,
            idempotency_key=f"djen-poll:{slot}",
            max_attempts=settings.job_max_attempts,
        )


def enqueue_refresh(
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    idempotency_key: str | None = None,
) -> str | None:
    settings = settings or get_settings()
    tz = ZoneInfo(settings.tz)
    now = now or datetime.now(tz)
    # slots :00 / :30
    minute = 0 if now.minute < 30 else 30
    slot = now.replace(minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    key = idempotency_key or f"refresh:{slot}"
    with session_scope() as session:
        repo = Repository(session)
        return _enqueue(
            repo,
            run_type=RunType.PROCESS_REFRESH.value,
            job_type=JobType.PROCESS_REFRESH.value,
            idempotency_key=key,
            max_attempts=settings.job_max_attempts,
        )


def enqueue_diary_sweep(*, settings: Settings | None = None, now: datetime | None = None) -> str | None:
    settings = settings or get_settings()
    tz = ZoneInfo(settings.tz)
    now = now or datetime.now(tz)
    day = now.date().isoformat()
    with session_scope() as session:
        repo = Repository(session)
        return _enqueue(
            repo,
            run_type=RunType.DIARY_SWEEP.value,
            job_type=JobType.DIARY_SWEEP.value,
            idempotency_key=f"diary:{day}",
            max_attempts=settings.job_max_attempts,
        )


def enqueue_national_reconciliation(
    *, settings: Settings | None = None, now: datetime | None = None
) -> str | None:
    settings = settings or get_settings()
    tz = ZoneInfo(settings.tz)
    now = now or datetime.now(tz)
    iso = now.isocalendar()
    key = f"recon:{iso.year}-W{iso.week:02d}"
    with session_scope() as session:
        repo = Repository(session)
        return _enqueue(
            repo,
            run_type=RunType.NATIONAL_RECONCILIATION.value,
            job_type=JobType.NATIONAL_RECONCILIATION.value,
            idempotency_key=key,
            max_attempts=settings.job_max_attempts,
        )


def _due_for_hourly(last: datetime | None, now: datetime, interval_minutes: int) -> bool:
    if last is None:
        return True
    return (now - last).total_seconds() >= interval_minutes * 60


def _due_diary_0630(last_day: str | None, now: datetime) -> bool:
    if now.hour < 6 or (now.hour == 6 and now.minute < 30):
        return False
    day = now.date().isoformat()
    return last_day != day


def _due_weekly(last_week: str | None, now: datetime) -> bool:
    iso = now.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    return last_week != week


def scheduler_tick(
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Uma passagem do scheduler (testável). Mutates `state` com últimos slots."""
    settings = settings or get_settings()
    tz = ZoneInfo(settings.tz)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    state = state if state is not None else {}
    cfg = _jobs_cfg(settings)
    enqueued: dict[str, str | None] = {}

    # DJEN_POLL hourly
    if _job_enabled(cfg, "DJEN_POLL"):
        interval = int((cfg.get("DJEN_POLL") or {}).get("interval_minutes") or 60)
        last = state.get("last_djen_poll_at")
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except ValueError:
                last = None
        if _due_for_hourly(last if isinstance(last, datetime) else None, now, interval):
            jid = enqueue_djen_poll(settings=settings, now=now)
            enqueued["DJEN_POLL"] = jid
            if jid:
                state["last_djen_poll_at"] = now.isoformat()

    # PROCESS_REFRESH every 30 min
    if _job_enabled(cfg, "PROCESS_REFRESH"):
        last = state.get("last_refresh_slot")
        minute = 0 if now.minute < 30 else 30
        slot = now.replace(minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        if last != slot:
            jid = enqueue_refresh(settings=settings, now=now)
            enqueued["PROCESS_REFRESH"] = jid
            if jid:
                state["last_refresh_slot"] = slot

    # DIARY_SWEEP daily 06:30
    if _job_enabled(cfg, "DIARY_SWEEP"):
        if _due_diary_0630(state.get("last_diary_day"), now):
            jid = enqueue_diary_sweep(settings=settings, now=now)
            enqueued["DIARY_SWEEP"] = jid
            if jid:
                state["last_diary_day"] = now.date().isoformat()

    # NATIONAL_RECONCILIATION weekly
    if _job_enabled(cfg, "NATIONAL_RECONCILIATION"):
        iso = now.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        if _due_weekly(state.get("last_recon_week"), now):
            jid = enqueue_national_reconciliation(settings=settings, now=now)
            enqueued["NATIONAL_RECONCILIATION"] = jid
            if jid:
                state["last_recon_week"] = week

    # DAILY_DIGEST via cron
    if _job_enabled(cfg, "DAILY_DIGEST"):
        expr = _cron_expr(settings)
        next_digest: datetime | None = state.get("next_digest_at")
        if isinstance(next_digest, str):
            try:
                next_digest = datetime.fromisoformat(next_digest)
            except ValueError:
                next_digest = None
        if next_digest is None:
            cron = croniter(expr, now)
            next_digest = cron.get_next(datetime)
            state["next_digest_at"] = next_digest.isoformat()
        elif now >= next_digest:
            jid = enqueue_daily_digest(settings=settings)
            enqueued["DAILY_DIGEST"] = jid
            cron = croniter(expr, now)
            nxt = cron.get_next(datetime)
            state["next_digest_at"] = nxt.isoformat()

    return {"enqueued": enqueued, "state": state, "now": now.isoformat()}


def scheduler_loop() -> None:
    setup_logging()
    init_db()
    settings = get_settings()
    state: dict[str, Any] = {}
    logger.info(
        "scheduler_started",
        extra={
            "extra": {
                "cron": _cron_expr(settings),
                "tz": settings.tz,
                "jobs": list(_jobs_cfg(settings).keys()),
            }
        },
    )
    while True:
        try:
            result = scheduler_tick(settings=settings, state=state)
            for jt, jid in (result.get("enqueued") or {}).items():
                if jid:
                    logger.info("job_enqueued", extra={"extra": {"job_type": jt, "job_id": jid}})
        except Exception as exc:  # noqa: BLE001
            logger.error("schedule_tick_failed", extra={"extra": {"err": str(exc)}})
        time.sleep(20)


def main() -> None:
    scheduler_loop()


if __name__ == "__main__":
    main()
