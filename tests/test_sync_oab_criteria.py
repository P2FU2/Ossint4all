from monitor_jus.db.models import Criterion
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.pipeline.bootstrap import sync_criteria_detailed
from monitor_jus.web.services.criteria import sync_criteria


def _db(tmp_path, monkeypatch, name: str = "sync_oab.db"):
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


def test_sync_does_not_convert_2556a_to_2556(tmp_path, monkeypatch):
    """RJ-2556A nunca é convertido automaticamente em RJ-2556."""
    url = _db(tmp_path, monkeypatch)
    yaml_path = tmp_path / "mon.yaml"
    yaml_path.write_text(
        """
monitoramentos:
  oabs:
    - numero: "2556"
      seccional: "RJ"
      responsavel: "Fernando"
      sufixo: null
  nomes: []
  cpfs: []
  processos: []
  empresas: []
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MONITORAMENTOS_PATH", str(yaml_path))
    from monitor_jus.config import get_settings

    get_settings.cache_clear()

    with session_scope(url) as session:
        session.add(
            Criterion(
                id="c1",
                criterion_type="OAB",
                value="RJ:2556A",
                label="Old",
                active=True,
                meta={"seccional": "RJ", "numero": "2556A"},
            )
        )
        session.flush()

        settings = get_settings()
        result = sync_criteria_detailed(session, settings)
        assert "RJ:2556" in result["yaml_oabs"]
        assert result["changes"] >= 1

        old = session.get(Criterion, "c1")
        assert old is not None
        assert old.value == "RJ:2556A"  # não convertido

        from sqlalchemy import select

        created = session.scalar(
            select(Criterion).where(Criterion.value == "RJ:2556")
        )
        assert created is not None
        assert created.active is True


def test_sync_survives_backfill_failure(tmp_path, monkeypatch):
    url = _db(tmp_path, monkeypatch, "sync_bf.db")
    yaml_path = tmp_path / "mon2.yaml"
    yaml_path.write_text(
        """
monitoramentos:
  oabs:
    - numero: "2556"
      seccional: "RJ"
  nomes: []
  cpfs: []
  processos: []
  empresas: []
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MONITORAMENTOS_PATH", str(yaml_path))
    from monitor_jus.config import get_settings

    get_settings.cache_clear()

    with session_scope(url) as session:
        settings = get_settings()

        def boom(_session):
            raise RuntimeError("backfill explode")

        monkeypatch.setattr(
            "monitor_jus.pipeline.discovery.backfill_oab_links_from_payloads",
            boom,
        )
        result = sync_criteria(session, settings)
        assert result["backfill_error"]
        from sqlalchemy import select

        created = session.scalar(select(Criterion).where(Criterion.value == "RJ:2556"))
        assert created is not None
