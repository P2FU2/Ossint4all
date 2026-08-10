"""Agregação de saúde de cobertura por critério."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from monitor_jus.db.models import Criterion, SourceCheckpoint, SourceRun
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.web.services.coverage_health import (
    coverage_attention,
    criterion_poll_health,
    digest_source_health,
)


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'cov.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def _run(
    *,
    criteria_id: str,
    status: str,
    finished_at: datetime,
    hit_max_pages: bool = False,
) -> SourceRun:
    return SourceRun(
        id=str(uuid4()),
        job_type="DJEN_POLL",
        source="DJEN",
        criteria_id=criteria_id,
        started_at=finished_at - timedelta(minutes=1),
        finished_at=finished_at,
        status=status,
        cursor_json={"hit_max_pages": hit_max_pages, "pages_fetched": 2},
    )


def test_criterion_poll_health_badges(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    with session_scope(url) as session:
        session.add(Criterion(id="ok1", criterion_type="OAB", value="SP:1", active=True))
        session.add(Criterion(id="fail1", criterion_type="OAB", value="RJ:2", active=True))
        session.add(Criterion(id="never1", criterion_type="NOME", value="Fulano", active=True))
        session.add(_run(criteria_id="ok1", status="SUCCESS", finished_at=now - timedelta(hours=1)))
        session.add(
            _run(
                criteria_id="fail1",
                status="FAILED",
                finished_at=now - timedelta(minutes=30),
            )
        )
        session.flush()

    with session_scope(url) as session:
        health = criterion_poll_health(session, now=now)
        assert health["ok1"]["badge"] == "ok"
        assert health["fail1"]["badge"] == "falhou"
        assert "never1" not in health  # sem runs → tratado no digest/attention


def test_coverage_attention_and_digest(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    with session_scope(url) as session:
        session.add(Criterion(id="stale1", criterion_type="OAB", value="DF:3", active=True))
        session.add(Criterion(id="sat1", criterion_type="OAB", value="SP:9", active=True))
        session.add(
            _run(
                criteria_id="stale1",
                status="SUCCESS",
                finished_at=now - timedelta(hours=5),
            )
        )
        session.add(
            _run(
                criteria_id="sat1",
                status="SUCCESS",
                finished_at=now - timedelta(hours=1),
                hit_max_pages=True,
            )
        )
        session.add(
            SourceCheckpoint(
                id="cp1",
                source="djen",
                checkpoint_key="last_poll_success",
                cursor={"until": "2026-08-09", "at": (now - timedelta(hours=5)).isoformat()},
                updated_at=now - timedelta(hours=5),
            )
        )
        session.flush()

    with session_scope(url) as session:
        alerts = coverage_attention(session, djen_enabled=True, now=now)
        texts = " | ".join(a["text"] for a in alerts)
        assert "sem sucesso DJEN" in texts or "atrasado" in texts.lower() or "DF:3" in texts
        assert "max_pages" in texts
        assert "Checkpoint DJEN" in texts

        digest = digest_source_health(session, now=now)
        assert digest["total"] == 2
        assert digest["ok"] == 1
        assert digest["stale"] == 1
        assert digest["has_issues"] is True


def test_recent_source_failures_include_criterion(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    with session_scope(url) as session:
        session.add(Criterion(id="c1", criterion_type="OAB", value="SP:10", active=True))
        session.add(
            SourceRun(
                id=str(uuid4()),
                job_type="DJEN_POLL",
                source="DJEN",
                criteria_id="c1",
                started_at=now - timedelta(hours=1),
                finished_at=now - timedelta(hours=1),
                status="FAILED",
                error_message="boom",
            )
        )
        session.flush()

    with session_scope(url) as session:
        from monitor_jus.report.html_report import recent_source_failures

        rows = recent_source_failures(session, hours=48)
        assert rows
        assert rows[0]["criterion"] == "OAB:SP:10"
        assert rows[0]["job_type"] == "DJEN_POLL"
