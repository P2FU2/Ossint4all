from sqlalchemy import select

from osint4all.db.history import clear_searches, list_searches, record_search, replay_mode, replay_spec
from osint4all.db.models import User
from osint4all.web.auth import seed_admin_user


def test_replay_mode_maps_tools() -> None:
    assert replay_mode("auto", "PLATE") == "auto"
    assert replay_mode("PLATE", "PLATE") == "PLATE"
    assert replay_mode("email", "EMAIL") == "EMAIL"
    assert replay_mode("massa", "massa") == "massa"
    assert replay_mode("unknown", "CNPJ") == "CNPJ"
    crt = replay_spec("crtsh", "URL")
    assert crt["action"] == "/app/ferramentas/executar"
    assert crt["tool"] == "crtsh"
    plate = replay_spec("PLATE", "PLATE")
    assert plate["action"] == "/app/consultar"
    assert plate["tool"] == ""
    domain = replay_spec("URL", "URL")
    assert domain["tool"] == "crtsh"
    assert domain["action"] == "/app/ferramentas/executar"


def test_record_list_and_clear(db, settings) -> None:
    seed_admin_user(db, settings)
    user = db.scalar(select(User).where(User.username == "admin"))
    assert user is not None
    assert record_search(db, user, query="  ") is None
    row = record_search(
        db,
        user,
        query="ABC1D23",
        mode="PLATE",
        kind="PLATE",
        title="Placa ABC1D23",
        summary="Série SP",
        ok=True,
    )
    assert row is not None
    rows = list_searches(db, user)
    assert len(rows) == 1
    assert rows[0].query == "ABC1D23"
    assert rows[0].kind == "PLATE"
    again = record_search(
        db,
        user,
        query="ABC1D23",
        mode="PLATE",
        kind="PLATE",
        title="Placa atualizada",
        summary="replay",
        ok=True,
    )
    assert again is not None
    assert again.id == row.id
    assert list_searches(db, user)[0].title == "Placa atualizada"
    assert clear_searches(db, user) == 1
    assert list_searches(db, user) == []
