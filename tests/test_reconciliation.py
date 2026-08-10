"""NATIONAL_RECONCILIATION: flags, clear e enqueue de refresh."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import select

from monitor_jus.db.models import Job
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import JobType
from monitor_jus.pipeline import reconciliation as recon_mod


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'recon.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_reconciliation_clears_flag_and_enqueues_refresh(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(recon_mod, "run_diary_sweep", lambda *a, **k: {"ok": True})

    def fake_route(cnj, tribunal=None, settings=None):
        if "STF" in (tribunal or ""):
            return SimpleNamespace(
                source="DJEN_ONLY", requires_reconciliation=True, datajud_alias=None
            )
        return SimpleNamespace(
            source="DATAJUD", requires_reconciliation=False, datajud_alias="api_publica_tjsp"
        )

    monkeypatch.setattr(recon_mod, "resolve_process_source", fake_route)

    with session_scope(url) as session:
        repo = Repository(session)
        ok = repo.upsert_process(
            "1000123-45.2023.8.26.0100",
            "10001234520238260100",
            tribunal="TJSP",
            requires_reconciliation=True,
        )
        bad = repo.upsert_process(
            "0000123-45.2023.1.00.0000",
            "00001234520231000000",
            tribunal="STF",
        )
        ok.next_check_at = None
        session.flush()

    with session_scope(url) as session:
        summary = recon_mod.run_national_reconciliation(session)
        assert summary["cleared_reconciliation"] == 1
        assert summary["flagged_reconciliation"] == 1
        assert summary["refresh_enqueued"] is True
        jobs = list(
            session.scalars(
                select(Job).where(Job.job_type == JobType.PROCESS_REFRESH.value)
            ).all()
        )
        assert len(jobs) == 1
        from monitor_jus.db.models import Process

        proc_ok = session.scalar(
            select(Process).where(Process.numero_cnj == "1000123-45.2023.8.26.0100")
        )
        assert proc_ok is not None
        assert proc_ok.requires_reconciliation is False
        proc_bad = session.scalar(
            select(Process).where(Process.numero_cnj == "0000123-45.2023.1.00.0000")
        )
        assert proc_bad is not None
        assert proc_bad.requires_reconciliation is True
        _ = bad


def test_reconciliation_no_refresh_when_already_active(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(recon_mod, "run_diary_sweep", lambda *a, **k: {})
    monkeypatch.setattr(
        recon_mod,
        "resolve_process_source",
        lambda *a, **k: SimpleNamespace(
            source="DATAJUD", requires_reconciliation=False, datajud_alias="x"
        ),
    )
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("PROCESS_REFRESH", trigger_type="test", run_mode="LIVE")
        repo.enqueue_job(run.id, JobType.PROCESS_REFRESH.value, idempotency_key="active")
        repo.upsert_process(
            "1000123-45.2023.8.26.0100",
            "10001234520238260100",
            tribunal="TJSP",
        )
        session.flush()

    with session_scope(url) as session:
        summary = recon_mod.run_national_reconciliation(session)
        assert summary["refresh_enqueued"] is False
