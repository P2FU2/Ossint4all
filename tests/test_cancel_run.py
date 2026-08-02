from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import JobStatus, RunStatus
from monitor_jus.web.services.actions import cancel_job, cancel_run


def _db(tmp_path, monkeypatch, name: str = "cancel.db"):
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_cancel_run_stops_bootstrap(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("BOOTSTRAP", "ui")
        repo.enqueue_job(run.id, "BOOTSTRAP", max_attempts=3)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        assert claimed.status == JobStatus.RUNNING.value

        result = cancel_run(session, run_id=run.id, username="admin")
        assert result["jobs_cancelled"] == 1
        assert claimed.status == JobStatus.CANCELLED.value
        assert run.status == RunStatus.CANCELLED.value


def test_cancel_job_individual(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch, "cancel_job.db")
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("HISTORICAL_DISCOVERY", "ui")
        job = repo.enqueue_job(run.id, "HISTORICAL_DISCOVERY", max_attempts=3)
        result = cancel_job(session, job_id=job.id, username="admin")
        assert result["status"] == JobStatus.CANCELLED.value
        assert job.status == JobStatus.CANCELLED.value
        assert run.status == RunStatus.CANCELLED.value


def test_cancel_run_already_done_raises(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch, "cancel_done.db")
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("DAILY_DIGEST", "ui")
        job = repo.enqueue_job(run.id, "DAILY_DIGEST", max_attempts=3)
        job.status = JobStatus.SUCCESS.value
        run.status = RunStatus.SUCCESS.value
        session.flush()
        try:
            cancel_run(session, run_id=run.id, username="admin")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "nada a cancelar" in str(exc).lower()
