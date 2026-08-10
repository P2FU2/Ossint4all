"""Digest: só novidades + retry sem duplicar eventos."""

from __future__ import annotations

from sqlalchemy import func, select

from monitor_jus.db.models import Digest, Event
from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.exceptions import RecoverableJobError
from monitor_jus.models import DigestStatus, NotifyStatus
from monitor_jus.pipeline.digest import _digest_subject, build_and_send_digest
from monitor_jus.report.html_report import render_digest_html


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'd.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_digest_subject_formats():
    assert "nenhuma novidade" in _digest_subject("2026-08-09", 0)
    assert "12 novidades" in _digest_subject("2026-08-09", 12)
    assert "09/08/2026" in _digest_subject("2026-08-09", 1)


def test_email_html_has_no_acervo_table():
    html = render_digest_html([], zero=True, failures=[])
    assert "Processos monitorados" not in html
    assert "Estatísticas por OAB" not in html
    assert "acervo completo" not in html.lower()
    assert "Nenhuma novidade processual" in html


def test_digest_retry_does_not_duplicate_events(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_TO", "a@b.com")
    from monitor_jus.config import get_settings

    get_settings.cache_clear()

    with session_scope(url) as session:
        repo = Repository(session)
        for i in range(3):
            repo.create_event(
                event_type="PUBLICACAO_DJEN",
                event_identity_key=f"k{i}",
                notify_status=NotifyStatus.PENDING_NOTIFY.value,
                source_name="djen",
                payload_hash=f"h{i}",
                title=f"t{i}",
                description="d",
                priority="media",
                numero_cnj=f"100000{i}-00.2023.8.26.0100",
                tribunal="TJSP",
            )
        session.flush()

    calls = {"n": 0}

    def fake_send(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("smtp down")
        return {"message_id": "msg-1", "attachments": 1}

    monkeypatch.setattr("monitor_jus.pipeline.digest.send_html_email", fake_send)

    with session_scope(url) as session:
        try:
            build_and_send_digest(session)
            raise AssertionError("should raise RecoverableJobError")
        except RecoverableJobError:
            pass
        repo = Repository(session)
        open_d = repo.find_open_delivery_digest()
        assert open_d is not None
        assert open_d.status == DigestStatus.DELIVERY_PENDING.value
        digest_a_id = open_d.id
        events = list(session.scalars(select(Event)).all())
        assert all(e.notify_status == NotifyStatus.IN_DIGEST.value for e in events)

    with session_scope(url) as session:
        result = build_and_send_digest(session)
        assert result["status"] == "SENT"
        assert result["digest_id"] == digest_a_id
        n_digests = session.scalar(select(func.count()).select_from(Digest))
        assert int(n_digests or 0) == 1
        events = list(session.scalars(select(Event)).all())
        assert len(events) == 3
        assert all(e.notify_status == NotifyStatus.NOTIFIED.value for e in events)
