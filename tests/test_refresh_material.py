"""PROCESS_REFRESH: delta material vs fingerprint irrelevante."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from monitor_jus.db.repository import Repository
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.models import EventType, NotifyStatus
from monitor_jus.pipeline.tracking import (
    material_movement_changed,
    run_tracking,
    _material_state_from_norm,
)


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'r.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_refresh_non_material_change_does_not_create_event():
    prev = ("123", "2026-01-01T00:00:00", "publicacao", "vara 1", "")
    # só fingerprint/capa mudaria — movimento material igual
    cur = ("123", "2026-01-01T00:00:00", "publicacao", "vara 1", "")
    assert material_movement_changed(prev, cur) is False


def test_refresh_material_movement_creates_single_event(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DATAJUD_ENABLE", "true")
    monkeypatch.setenv("DATAJUD_MODE", "selective")
    from monitor_jus.config import get_settings

    get_settings.cache_clear()

    with session_scope(url) as session:
        repo = Repository(session)
        proc = repo.upsert_process(
            "1000123-45.2023.8.26.0100",
            "10001234520238260100",
            tribunal="TJSP",
            payload={
                "datajud": {
                    "last_movement_code": "1",
                    "last_movement_date": "2025-01-01T00:00:00.000Z",
                    "last_movement_name": "Distribuição",
                    "orgao_julgador": "1ª Vara",
                }
            },
        )
        proc.next_check_at = None
        session.flush()

    hit = {
        "grau": "G1",
        "tribunal": "TJSP",
        "numeroProcesso": "10001234520238260100",
        "classe": {"nome": "Procedimento Comum"},
        "orgaoJulgador": {"nome": "1ª Vara"},
        "movimentos": [
            {
                "codigo": "85",
                "nome": "Juntada de Petição",
                "dataHora": "2026-08-01T12:00:00.000Z",
            }
        ],
    }

    class FakeClient:
        def search_all_by_cnj(self, cnj, alias=None):
            return [hit]

    monkeypatch.setattr(
        "monitor_jus.pipeline.tracking.DataJudClient",
        lambda settings: FakeClient(),
    )
    monkeypatch.setattr(
        "monitor_jus.pipeline.tracking.resolve_process_source",
        lambda *a, **k: SimpleNamespace(source="DATAJUD", datajud_alias="api_publica_tjsp"),
    )

    with session_scope(url) as session:
        result = run_tracking(session, parent_job_id="job-test-1", batch_size=10)
        assert result["events_created"] == 1
        assert result["refreshed"] == 1
        from sqlalchemy import select
        from monitor_jus.db.models import Event

        events = list(
            session.scalars(
                select(Event).where(Event.event_type == EventType.MOVIMENTACAO_PROCESSUAL.value)
            ).all()
        )
        assert len(events) == 1
        assert events[0].notify_status == NotifyStatus.PENDING_NOTIFY.value


def test_refresh_same_movement_twice_is_deduped(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DATAJUD_ENABLE", "true")
    from monitor_jus.config import get_settings

    get_settings.cache_clear()

    hit = {
        "grau": "G1",
        "tribunal": "TJSP",
        "numeroProcesso": "10001234520238260100",
        "classe": {"nome": "Procedimento Comum"},
        "orgaoJulgador": {"nome": "1ª Vara"},
        "movimentos": [
            {
                "codigo": "85",
                "nome": "Juntada de Petição",
                "dataHora": "2026-08-01T12:00:00.000Z",
            }
        ],
    }

    class FakeClient:
        def search_all_by_cnj(self, cnj, alias=None):
            return [hit]

    monkeypatch.setattr(
        "monitor_jus.pipeline.tracking.DataJudClient",
        lambda settings: FakeClient(),
    )
    monkeypatch.setattr(
        "monitor_jus.pipeline.tracking.resolve_process_source",
        lambda *a, **k: SimpleNamespace(source="DATAJUD", datajud_alias="api_publica_tjsp"),
    )

    with session_scope(url) as session:
        repo = Repository(session)
        repo.upsert_process(
            "1000123-45.2023.8.26.0100",
            "10001234520238260100",
            tribunal="TJSP",
        )
        session.flush()

    with session_scope(url) as session:
        r1 = run_tracking(session, parent_job_id="j1", batch_size=10)
        assert r1["events_created"] == 1

    with session_scope(url) as session:
        from sqlalchemy import func, select
        from monitor_jus.db.models import Event

        repo = Repository(session)
        for p in repo.list_processes():
            p.next_check_at = None
        session.flush()
        r2 = run_tracking(session, parent_job_id="j2", batch_size=10)
        assert r2["events_created"] == 0
        n = session.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.event_type == EventType.MOVIMENTACAO_PROCESSUAL.value)
        )
        assert int(n or 0) == 1


def test_refresh_batch_reenqueues_when_backlog_exists(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("DATAJUD_ENABLE", "true")
    from monitor_jus.config import get_settings

    get_settings.cache_clear()

    class FakeClient:
        def search_all_by_cnj(self, cnj, alias=None):
            return []

    monkeypatch.setattr(
        "monitor_jus.pipeline.tracking.DataJudClient",
        lambda settings: FakeClient(),
    )
    monkeypatch.setattr(
        "monitor_jus.pipeline.tracking.resolve_process_source",
        lambda *a, **k: SimpleNamespace(source="DATAJUD", datajud_alias="api_publica_tjsp"),
    )

    with session_scope(url) as session:
        repo = Repository(session)
        for i in range(3):
            repo.upsert_process(
                f"100012{i}-45.2023.8.26.0100",
                f"100012{i}4520238260100",
                tribunal="TJSP",
            )
        session.flush()

    with session_scope(url) as session:
        result = run_tracking(session, parent_job_id="parent-batch", batch_size=2)
        assert result["due"] == 2
        # 1 ainda due (próximos checks futuros nos 2 processados; o 3º ainda due)
        # na verdade os 2 processados ganham next_check; o 3º permanece due → remaining >= 1
        assert result["remaining_due"] >= 1
        assert result["requeued"] is True
        from sqlalchemy import select
        from monitor_jus.db.models import Job

        cont = session.scalar(
            select(Job).where(Job.idempotency_key == "refresh-cont:parent-batch")
        )
        assert cont is not None
