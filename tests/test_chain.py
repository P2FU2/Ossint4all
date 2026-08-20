from sqlalchemy import select

from osint4all.consult import run_consult
from osint4all.db.chain import alvo_fields, chain_view, identifiers_from_outcome, ingest_outcome, reset_chain
from osint4all.db.models import User
from osint4all.web.auth import seed_admin_user


def _user(db, settings) -> User:
    seed_admin_user(db, settings)
    user = db.scalar(select(User).where(User.username == "admin"))
    assert user is not None
    return user


def test_email_derives_username_key() -> None:
    email = run_consult("ana@exemplo.com", mode="EMAIL")
    keys = {item["key"] for item in identifiers_from_outcome(email)}
    assert "email:ana@exemplo.com" in keys
    assert "username:ana" in keys


def test_username_then_email_joins_chain(db, settings) -> None:
    user = _user(db, settings)
    social = run_consult("@ana", mode="USERNAME")
    ingest_outcome(db, user, social)
    first = chain_view(db, user, current_query="@ana")
    assert first is not None
    assert first["linked"] is False
    assert len(first["steps"]) == 1

    email = run_consult("ana@exemplo.com", mode="EMAIL")
    ingest_outcome(db, user, email)
    view = chain_view(db, user, current_query="ana@exemplo.com")
    assert view is not None
    assert view["linked"] is True
    assert view["just_linked"] is True
    assert len(view["steps"]) == 2
    assert any("ana" in item for item in view["shared"])
    titles = " ".join(step["title"] for step in view["steps"]).lower()
    assert "@ana" in titles
    assert "ana@exemplo.com" in titles
    assert any(item["label"] in {"@ana", "ana@exemplo.com"} or "ana" in item["label"] for item in view["idents"])
    assert "@ana" in view["export"]
    ingest_outcome(db, user, email)
    assert len(chain_view(db, user, current_query="ana@exemplo.com")["steps"]) == 2


def test_unrelated_plate_starts_new_chain(db, settings) -> None:
    user = _user(db, settings)
    ingest_outcome(db, user, run_consult("@ana", mode="USERNAME"))
    ingest_outcome(db, user, run_consult("ABC1D23", mode="PLATE"))
    view = chain_view(db, user, current_query="ABC1D23")
    assert view is not None
    assert view["linked"] is False
    assert len(view["steps"]) == 1
    assert "ABC1D23" in view["steps"][0]["query"].upper().replace("-", "")


def test_reset_chain(db, settings) -> None:
    user = _user(db, settings)
    ingest_outcome(db, user, run_consult("@ana", mode="USERNAME"))
    reset_chain(db, user)
    assert chain_view(db, user) is None


def test_alvo_fields_reads_username_from_email(db, settings) -> None:
    user = _user(db, settings)
    ingest_outcome(db, user, run_consult("pedromilani14@gmail.com", mode="EMAIL"))
    fields = alvo_fields(db, user)
    assert fields["EMAIL"] == "pedromilani14@gmail.com"
    assert fields["USERNAME"] == "pedromilani14"
