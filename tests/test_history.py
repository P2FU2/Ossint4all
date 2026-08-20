from sqlalchemy import select

from osint4all.db.history import clear_searches, list_searches, record_search, replay_mode
from osint4all.db.models import User
from osint4all.web.auth import seed_admin_user


def test_replay_mode_maps_tools() -> None:
    assert replay_mode("auto", "PLATE") == "auto"
    assert replay_mode("PLATE", "PLATE") == "PLATE"
    assert replay_mode("email", "EMAIL") == "EMAIL"
    assert replay_mode("massa", "massa") == "massa"
    assert replay_mode("unknown", "CNPJ") == "CNPJ"


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
    assert clear_searches(db, user) == 1
    assert list_searches(db, user) == []
