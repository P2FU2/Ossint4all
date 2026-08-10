"""Scheduler: idempotência de slot e barreira has_active_job."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from monitor_jus.db.models import Job
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import JobStatus, JobType
from monitor_jus.scheduler import enqueue_djen_poll, enqueue_refresh, scheduler_tick


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 's.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_scheduler_same_slot_is_idempotent(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime(2026, 8, 9, 21, 10, tzinfo=tz)
    a = enqueue_djen_poll(now=now)
    b = enqueue_djen_poll(now=now)
    assert a is not None and a == b
    with session_scope(url) as session:
        jobs = list(
            session.scalars(select(Job).where(Job.job_type == JobType.DJEN_POLL.value)).all()
        )
        assert len(jobs) == 1
        assert jobs[0].idempotency_key == "djen-poll:2026-08-09-21"


def test_scheduler_does_not_stack_running_job(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime(2026, 8, 9, 21, 5, tzinfo=tz)
    first = enqueue_refresh(now=now)
    assert first is not None
    with session_scope(url) as session:
        repo = Repository(session)
        job = session.get(Job, first)
        assert job is not None
        job.status = JobStatus.RUNNING.value
        session.flush()
        assert repo.has_active_job(JobType.PROCESS_REFRESH.value)

    later = datetime(2026, 8, 9, 21, 35, tzinfo=tz)
    blocked = enqueue_refresh(now=later)
    assert blocked is None


def test_scheduler_tick_enqueues_refresh_slot(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime(2026, 8, 9, 21, 31, tzinfo=tz)
    state: dict = {}
    result = scheduler_tick(now=now, state=state)
    assert result["enqueued"].get("PROCESS_REFRESH")
    assert state.get("last_refresh_slot") == "2026-08-09T21:30"
    result2 = scheduler_tick(now=now, state=state)
    assert result2["enqueued"].get("PROCESS_REFRESH") is None
