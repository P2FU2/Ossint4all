from sqlalchemy import select

from osint4all.consult import run_consult
from osint4all.db.chain import (
    alvo_fields,
    chain_view,
    identifiers_from_outcome,
    ingest_outcome,
    reset_alvo_draft,
    reset_chain,
    save_alvo_fields,
)
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


def test_username_then_email_stay_separate(db, settings) -> None:
    user = _user(db, settings)
    ingest_outcome(db, user, run_consult("@ana", mode="USERNAME"))
    first = chain_view(db, user, current_query="@ana")
    assert first is not None
    assert first["linked"] is False
    assert len(first["steps"]) == 1

    ingest_outcome(db, user, run_consult("ana@exemplo.com", mode="EMAIL"))
    view = chain_view(db, user, current_query="ana@exemplo.com")
    assert view is not None
    assert view["linked"] is False
    assert len(view["steps"]) == 1
    assert "ana@exemplo.com" in (view["steps"][0]["query"] or "")
    assert all("@ana" not in (step["query"] or "") for step in view["steps"])


def test_repeat_same_query_updates_last(db, settings) -> None:
    user = _user(db, settings)
    email = run_consult("ana@exemplo.com", mode="EMAIL")
    ingest_outcome(db, user, email)
    ingest_outcome(db, user, email)
    view = chain_view(db, user, current_query="ana@exemplo.com")
    assert view is not None
    assert len(view["steps"]) == 1


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


def test_consult_does_not_fill_alvo(db, settings) -> None:
    user = _user(db, settings)
    ingest_outcome(db, user, run_consult("pedromilani14@gmail.com", mode="EMAIL"))
    assert alvo_fields(db, user) == {}


def test_alvo_fields_only_what_user_saved(db, settings) -> None:
    user = _user(db, settings)
    ingest_outcome(db, user, run_consult("pedromilani14@gmail.com", mode="EMAIL"))
    save_alvo_fields(db, user, {"EMAIL": "pedromilani14@gmail.com", "USERNAME": "pedromilani14"})
    fields = alvo_fields(db, user)
    assert fields["EMAIL"] == "pedromilani14@gmail.com"
    assert fields["USERNAME"] == "pedromilani14"
    ingest_outcome(db, user, run_consult("ABC1D23", mode="PLATE"))
    still = alvo_fields(db, user)
    assert still["EMAIL"] == "pedromilani14@gmail.com"
    assert "PLATE" not in still


def test_reset_alvo_draft(db, settings) -> None:
    user = _user(db, settings)
    save_alvo_fields(db, user, {"NAME": "Maria Silva Souza", "CPF": "390.533.447-05"})
    reset_alvo_draft(db, user)
    assert alvo_fields(db, user) == {}
