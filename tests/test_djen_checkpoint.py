"""DJEN checkpoint: só avança com 100% dos critérios OK."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from sqlalchemy import select

from monitor_jus.db.models import Criterion, SourceCheckpoint
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.pipeline import discovery as discovery_mod


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'c.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DJEN_ENABLE", "true")
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def _seed_criteria(session, n=2):
    for i in range(n):
        session.add(
            Criterion(
                id=f"c{i}",
                criterion_type="OAB",
                value=f"SP:{100000 + i}",
                label="T",
                active=True,
            )
        )
    session.flush()


def test_djen_partial_failure_keeps_checkpoint(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": True}
        raise RuntimeError("fonte fora")

    monkeypatch.setattr(discovery_mod, "DjenClient", lambda settings: MagicMock())
    monkeypatch.setattr(discovery_mod, "search_oab_nationally", boom)
    monkeypatch.setattr(
        discovery_mod,
        "_resolve_window",
        lambda *a, **k: (date(2026, 8, 1), date(2026, 8, 9)),
    )
    monkeypatch.setattr(discovery_mod, "_max_pages_for", lambda *a, **k: 5)
    monkeypatch.setattr(
        discovery_mod,
        "_search_flags",
        lambda *a, **k: {"OAB": True, "NOME": False, "PROCESSO": False, "CNPJ": False, "EMPRESA": False},
    )
    # checkpoint prévio
    with session_scope(url) as session:
        session.add(
            SourceCheckpoint(
                id="cp1",
                source="djen",
                checkpoint_key="last_poll_success",
                cursor={"until": "2026-08-01"},
            )
        )
        _seed_criteria(session, 2)

    with session_scope(url) as session:
        summary = discovery_mod.run_djen_poll(session, mode="incremental")
        assert summary["checkpoint_advanced"] is False
        assert summary["successful_criteria"] == 1
        assert summary["total_active_criteria"] == 2
        cp = session.scalar(
            select(SourceCheckpoint).where(
                SourceCheckpoint.source == "djen",
                SourceCheckpoint.checkpoint_key == "last_poll_success",
            )
        )
        assert cp is not None
        assert (cp.cursor or {}).get("until") == "2026-08-01"


def test_djen_full_success_advances_checkpoint(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(discovery_mod, "DjenClient", lambda settings: MagicMock())
    monkeypatch.setattr(
        discovery_mod, "search_oab_nationally", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        discovery_mod,
        "_resolve_window",
        lambda *a, **k: (date(2026, 8, 1), date(2026, 8, 9)),
    )
    monkeypatch.setattr(discovery_mod, "_max_pages_for", lambda *a, **k: 5)
    monkeypatch.setattr(
        discovery_mod,
        "_search_flags",
        lambda *a, **k: {"OAB": True, "NOME": False, "PROCESSO": False, "CNPJ": False, "EMPRESA": False},
    )

    with session_scope(url) as session:
        _seed_criteria(session, 2)

    with session_scope(url) as session:
        summary = discovery_mod.run_djen_poll(session, mode="incremental")
        assert summary["checkpoint_advanced"] is True
        assert summary["successful_criteria"] == 2
        cp = session.scalar(
            select(SourceCheckpoint).where(
                SourceCheckpoint.source == "djen",
                SourceCheckpoint.checkpoint_key == "last_poll_success",
            )
        )
        assert cp is not None
        assert (cp.cursor or {}).get("until") == "2026-08-09"


def test_djen_soft_error_keeps_checkpoint(tmp_path, monkeypatch):
    """Retorno {"error": ...} não conta como sucesso nem avança checkpoint."""
    url = _db(tmp_path, monkeypatch)
    calls = {"n": 0}

    def soft(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"received": 0, "created": 0, "updated": 0, "rejected": 0}
        return {"error": "fonte fora (soft)"}

    monkeypatch.setattr(discovery_mod, "DjenClient", lambda settings: MagicMock())
    monkeypatch.setattr(discovery_mod, "search_oab_nationally", soft)
    monkeypatch.setattr(
        discovery_mod,
        "_resolve_window",
        lambda *a, **k: (date(2026, 8, 1), date(2026, 8, 9)),
    )
    monkeypatch.setattr(discovery_mod, "_max_pages_for", lambda *a, **k: 5)
    monkeypatch.setattr(
        discovery_mod,
        "_search_flags",
        lambda *a, **k: {"OAB": True, "NOME": False, "PROCESSO": False, "CNPJ": False, "EMPRESA": False},
    )
    with session_scope(url) as session:
        session.add(
            SourceCheckpoint(
                id="cp1",
                source="djen",
                checkpoint_key="last_poll_success",
                cursor={"until": "2026-08-01"},
            )
        )
        _seed_criteria(session, 2)

    with session_scope(url) as session:
        summary = discovery_mod.run_djen_poll(session, mode="incremental")
        assert summary["checkpoint_advanced"] is False
        assert summary["successful_criteria"] == 1
        assert len(summary["errors"]) == 1
        cp = session.scalar(
            select(SourceCheckpoint).where(
                SourceCheckpoint.source == "djen",
                SourceCheckpoint.checkpoint_key == "last_poll_success",
            )
        )
        assert (cp.cursor or {}).get("until") == "2026-08-01"


def test_search_oab_all_variants_fail_returns_error(tmp_path, monkeypatch):
    from monitor_jus.exceptions import FailedSource

    url = _db(tmp_path, monkeypatch)
    client = MagicMock()
    client.search_all_pages.side_effect = FailedSource("DJEN HTTP 503")

    with session_scope(url) as session:
        crit = Criterion(
            id="c0",
            criterion_type="OAB",
            value="SP:138094",
            label="Test",
            active=True,
        )
        session.add(crit)
        session.flush()
        from monitor_jus.config import get_settings

        out = discovery_mod.search_oab_nationally(
            session,
            client,
            crit,
            available_from=date(2026, 8, 1),
            available_until=date(2026, 8, 9),
            bootstrap_mode=False,
            settings=get_settings(),
            max_pages=2,
        )
        assert "error" in out
        assert client.search_all_pages.call_count >= 2


def test_djen_hit_max_pages_recorded_in_summary(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(discovery_mod, "DjenClient", lambda settings: MagicMock())
    monkeypatch.setattr(
        discovery_mod,
        "search_oab_nationally",
        lambda *a, **k: {"received": 10, "hit_max_pages": True},
    )
    monkeypatch.setattr(
        discovery_mod,
        "_resolve_window",
        lambda *a, **k: (date(2026, 8, 1), date(2026, 8, 9)),
    )
    monkeypatch.setattr(discovery_mod, "_max_pages_for", lambda *a, **k: 5)
    monkeypatch.setattr(
        discovery_mod,
        "_search_flags",
        lambda *a, **k: {"OAB": True, "NOME": False, "PROCESSO": False, "CNPJ": False, "EMPRESA": False},
    )
    with session_scope(url) as session:
        _seed_criteria(session, 1)

    with session_scope(url) as session:
        summary = discovery_mod.run_djen_poll(session, mode="incremental")
        assert summary["checkpoint_advanced"] is True
        assert summary["saturated_criteria"] == ["OAB:SP:100000"]
