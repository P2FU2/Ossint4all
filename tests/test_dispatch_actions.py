"""Exclusão mútua e mapeamento dos botões Disparar."""

from __future__ import annotations

import pytest

from monitor_jus.config import get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import JobStatus
from monitor_jus.web.services.actions import (
    assert_heavy_job_allowed,
    enqueue_from_ui,
)


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'disp.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_djen_poll_does_not_block_discovery(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("DJEN_POLL", "test")
        job = repo.enqueue_job(run.id, "DJEN_POLL", max_attempts=3)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        assert claimed.status == JobStatus.RUNNING.value

        # Poll horário NÃO deve bloquear Discovery
        assert_heavy_job_allowed(session, "HISTORICAL_DISCOVERY")


def test_bootstrap_blocks_discovery(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("BOOTSTRAP", "test")
        repo.enqueue_job(run.id, "BOOTSTRAP", max_attempts=3)
        with pytest.raises(ValueError, match="Bootstrap ou Discovery"):
            assert_heavy_job_allowed(session, "HISTORICAL_DISCOVERY")


def test_reconciliation_ui_maps_to_national(tmp_path, monkeypatch):
    from sqlalchemy import select

    from monitor_jus.db.models import Job

    url = _db(tmp_path, monkeypatch)
    settings = get_settings()
    with session_scope(url) as session:
        out = enqueue_from_ui(
            session,
            settings,
            run_type="RECONCILIATION",
            username="admin",
        )
        assert out["job_type"] == "NATIONAL_RECONCILIATION"
        job = session.scalar(select(Job).order_by(Job.created_at.desc()))
        assert job is not None
        assert job.job_type == "NATIONAL_RECONCILIATION"


def test_refresh_blocked_if_already_active(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    settings = get_settings()
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("PROCESS_REFRESH", "test")
        repo.enqueue_job(run.id, "PROCESS_REFRESH", max_attempts=3)
        with pytest.raises(ValueError, match="PROCESS_REFRESH"):
            enqueue_from_ui(
                session,
                settings,
                run_type="PROCESS_REFRESH",
                username="admin",
            )
