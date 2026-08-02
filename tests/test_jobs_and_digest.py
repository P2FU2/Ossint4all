from datetime import datetime, timezone

from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import DigestStatus, JobStatus, NotifyStatus


def test_job_retry_and_dead(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(f"sqlite:///{db.as_posix()}")

    url = f"sqlite:///{db.as_posix()}"
    with session_scope(url) as session:
        repo = Repository(session)
        run = repo.create_run("DAILY_DIGEST", "cli")
        job = repo.enqueue_job(run.id, "DAILY_DIGEST", max_attempts=2)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        assert claimed.id == job.id
        repo.fail_job(
            claimed,
            error_code="TMP",
            error_message="fail",
            recoverable=True,
            retry_delay_seconds=0,
        )
        assert claimed.status == JobStatus.RETRY.value

    with session_scope(url) as session:
        repo = Repository(session)
        claimed = repo.claim_next_job("w1")
        assert claimed is not None
        repo.fail_job(
            claimed,
            error_code="TMP",
            error_message="fail again",
            recoverable=True,
        )
        assert claimed.status == JobStatus.DEAD.value


def test_digest_marks_notified_only_after_sent(tmp_path, monkeypatch):
    db = tmp_path / "d.db"
    url = f"sqlite:///{db.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)

    with session_scope(url) as session:
        repo = Repository(session)
        ev = repo.create_event(
            event_type="MOVIMENTACAO_PROCESSUAL",
            event_identity_key="k1",
            notify_status=NotifyStatus.PENDING_NOTIFY.value,
            source_name="judit",
            payload_hash="h1",
            title="t",
            description="d",
            priority="alta",
        )
        digest = repo.create_digest(
            status=DigestStatus.BUILDING.value,
            reference_date="2026-08-01",
            total_events=1,
        )
        repo.attach_digest_items(digest.id, [ev.id])
        session.refresh(ev)
        assert ev.notify_status == NotifyStatus.IN_DIGEST.value
        digest.status = DigestStatus.DELIVERY_PENDING.value
        # ainda não notificado
        assert ev.notify_status == NotifyStatus.IN_DIGEST.value
        repo.mark_digest_sent(digest)
        session.refresh(ev)
        assert ev.notify_status == NotifyStatus.NOTIFIED.value
        cursor = repo.get_digest_cursor()
        assert cursor.last_successful_digest_at is not None
