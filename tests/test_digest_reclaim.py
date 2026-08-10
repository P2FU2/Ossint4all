"""Digest: reclaim BUILDING/HTML ausente + PENDING sem filtro de cursor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from monitor_jus.db.models import Digest, Event
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import DigestStatus, NotifyStatus
from monitor_jus.pipeline.digest import build_and_send_digest


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'd.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_TO", "a@b.com")
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_pending_notify_ignores_cursor_cutoff(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    old = datetime.now(timezone.utc) - timedelta(days=2)
    with session_scope(url) as session:
        repo = Repository(session)
        cursor = repo.get_digest_cursor()
        cursor.last_successful_digest_at = datetime.now(timezone.utc)
        ev = repo.create_event(
            event_type="PUBLICACAO_DJEN",
            event_identity_key="stale-pending",
            notify_status=NotifyStatus.PENDING_NOTIFY.value,
            source_name="djen",
            payload_hash="h1",
            title="t",
            description="d",
            priority="alta",
            numero_cnj="1000000-00.2023.8.26.0100",
            tribunal="TJSP",
        )
        ev.created_at = old
        session.flush()
        pending = repo.pending_notify_events(since=cursor.last_successful_digest_at)
        assert len(pending) == 1
        assert pending[0].priority == "alta"


def test_empty_digest_skips_email_without_alerts(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_send(**kwargs):
        calls["n"] += 1
        return {"message_id": "x", "attachments": 0}

    monkeypatch.setattr("monitor_jus.pipeline.digest.send_html_email", fake_send)
    monkeypatch.setattr(
        "monitor_jus.report.html_report.recent_source_failures",
        lambda session: [],
    )
    monkeypatch.setattr(
        "monitor_jus.report.html_report.format_source_failures_for_user",
        lambda failures: [],
    )
    monkeypatch.setattr(
        "monitor_jus.web.services.coverage_health.digest_source_health",
        lambda session: {
            "ok": 1,
            "stale": 0,
            "failed": 0,
            "never": 0,
            "total": 1,
            "has_issues": False,
            "rows": [],
            "headline": "ok",
            "detail": "",
        },
    )

    with session_scope(url) as session:
        result = build_and_send_digest(session)
        assert result["status"] == "SKIPPED_EMPTY"
        assert calls["n"] == 0


def test_building_digest_reclaimed_before_new_build(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "monitor_jus.pipeline.digest.send_html_email",
        lambda **kwargs: {"message_id": "m1", "attachments": 1},
    )
    with session_scope(url) as session:
        repo = Repository(session)
        ev = repo.create_event(
            event_type="PUBLICACAO_DJEN",
            event_identity_key="orphan",
            notify_status=NotifyStatus.IN_DIGEST.value,
            source_name="djen",
            payload_hash="h2",
            title="t",
            description="d",
            priority="media",
            numero_cnj="1000001-00.2023.8.26.0100",
            tribunal="TJSP",
        )
        stuck = repo.create_digest(
            reference_date="2026-08-09",
            status=DigestStatus.BUILDING.value,
            total_events=1,
        )
        repo.attach_digest_items(stuck.id, [ev.id])
        # attach_digest_items seta IN_DIGEST de novo
        session.flush()

    with session_scope(url) as session:
        result = build_and_send_digest(session)
        assert result["status"] == "SENT"
        failed = list(
            session.scalars(
                select(Digest).where(Digest.status == DigestStatus.FAILED.value)
            ).all()
        )
        assert len(failed) == 1
        events = list(session.scalars(select(Event)).all())
        assert all(e.notify_status == NotifyStatus.NOTIFIED.value for e in events)
        n = session.scalar(select(func.count()).select_from(Digest))
        assert int(n or 0) == 2  # FAILED + SENT
