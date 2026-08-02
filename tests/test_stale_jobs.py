from datetime import timedelta

from monitor_jus.db.repository import Repository, utcnow
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import JobStatus
from monitor_jus.web.services.actions import cleanup_stale_jobs, reap_stale_running_jobs
from monitor_jus.web.services.progress_board import build_progress_board


def _db(tmp_path, monkeypatch, name: str = "stale.db"):
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_reap_stale_running_never_progressed(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("BOOTSTRAP", "test")
        job = repo.enqueue_job(run.id, "BOOTSTRAP", max_attempts=3)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        # simula worker morto há horas, sem progresso
        old = utcnow() - timedelta(hours=8)
        claimed.started_at = old
        claimed.heartbeat_at = old
        claimed.progress_pct = 0
        claimed.progress_stage = "starting"
        session.flush()

        n = reap_stale_running_jobs(session, never_started_minutes=20.0)
        assert n == 1
        assert claimed.status == JobStatus.CANCELLED.value
        assert "heartbeat" in (claimed.last_error_message or "").lower() or "progresso" in (
            claimed.last_error_message or ""
        ).lower()


def test_healthy_running_not_reaped(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch, "ok.db")
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("HISTORICAL_DISCOVERY", "test")
        repo.enqueue_job(run.id, "HISTORICAL_DISCOVERY", max_attempts=3)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        claimed.progress_pct = 24
        claimed.progress_stage = "discovery_enrich"
        claimed.heartbeat_at = utcnow()
        session.flush()

        n = reap_stale_running_jobs(session)
        assert n == 0
        assert claimed.status == JobStatus.RUNNING.value


def test_progress_board_marks_stale_and_counts_healthy(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch, "board.db")
    with session_scope(url) as session:
        repo = Repository(session)
        run_b = repo.create_run("BOOTSTRAP", "test")
        job_b = repo.enqueue_job(run_b.id, "BOOTSTRAP", max_attempts=3)
        claimed_b = repo.claim_next_job("w1")
        assert claimed_b is not None
        old = utcnow() - timedelta(hours=8)
        claimed_b.started_at = old
        claimed_b.heartbeat_at = old
        claimed_b.progress_pct = 0
        claimed_b.progress_stage = "starting"

        run_d = repo.create_run("HISTORICAL_DISCOVERY", "test")
        job_d = repo.enqueue_job(run_d.id, "HISTORICAL_DISCOVERY", max_attempts=3)
        # claim precisa de PENDING — job_b já é RUNNING, então claim pega job_d
        claimed_d = repo.claim_next_job("w2")
        assert claimed_d is not None
        claimed_d.progress_pct = 24
        claimed_d.progress_stage = "discovery_enrich"
        claimed_d.heartbeat_at = utcnow()
        session.flush()

        board = build_progress_board(session)
        assert board["running_count"] == 1
        assert board["stale_count"] == 1
        assert board["headline"]["id"] == claimed_d.id
        stale_rows = [j for j in board["active"] if j["stale"]]
        assert len(stale_rows) == 1
        assert stale_rows[0]["status_label"] == "Travado"


def test_cleanup_allows_new_heavy_after_zombie(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch, "clean.db")
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("BOOTSTRAP", "test")
        repo.enqueue_job(run.id, "BOOTSTRAP", max_attempts=3)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        old = utcnow() - timedelta(hours=8)
        claimed.started_at = old
        claimed.heartbeat_at = old
        claimed.progress_pct = 0
        claimed.progress_stage = "starting"
        session.flush()

        cleaned = cleanup_stale_jobs(session)
        assert cleaned["running_reaped"] == 1

        from monitor_jus.web.services.actions import assert_heavy_job_allowed

        assert_heavy_job_allowed(session, "HISTORICAL_DISCOVERY")  # não levanta
