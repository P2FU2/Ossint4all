from monitor_jus.db.session import init_db, session_scope
from monitor_jus.pipeline.bootstrap import sync_criteria_from_config
from monitor_jus.pipeline.communication_ingest import ingest
from sqlalchemy import select
from monitor_jus.db.models import Communication


def test_poll_and_sweep_share_ingest_key(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from monitor_jus.config import get_settings

    get_settings.cache_clear()
    init_db(f"sqlite:///{db}")

    payload = {
        "id": "comm-1",
        "numeroProcesso": "1000123-45.2023.8.26.0100",
        "siglaTribunal": "TJSP",
        "texto": "Intimação ao advogado OAB/SP 138.094 Fernando Crespo Queiroz Neves",
        "dataDisponibilizacao": "2026-08-01",
    }

    with session_scope(f"sqlite:///{db}") as session:
        sync_criteria_from_config(session)
        r1 = ingest(
            session,
            source="DJEN",
            discovery_channel="OAB_SEARCH",
            raw_payload=payload,
            bootstrap_mode=True,
        )
        r2 = ingest(
            session,
            source="DJEN",
            discovery_channel="TRIBUNAL_SWEEP",
            raw_payload=payload,
            bootstrap_mode=True,
        )
        assert r1["created"] is True
        assert r2["updated"] is True
        assert r1["communication_key"] == r2["communication_key"]
        rows = list(session.scalars(select(Communication)).all())
        assert len(rows) == 1
        channels = rows[0].discovery_channels_json or []
        assert "OAB_SEARCH" in channels
        assert "TRIBUNAL_SWEEP" in channels

    get_settings.cache_clear()
