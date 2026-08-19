from osint4all.db.session import session_scope
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed
from osint4all.report.dossier import render_dossier_html
from osint4all.web.auth import hash_password, seed_admin_user, verify_password


def test_password_roundtrip() -> None:
    hashed = hash_password("secret")
    assert verify_password("secret", hashed)
    assert not verify_password("nope", hashed)


def test_seed_admin(settings) -> None:
    from sqlalchemy import select

    from osint4all.db.models import User

    with session_scope() as session:
        seed_admin_user(session, settings)
        seed_admin_user(session, settings)
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].role == "admin"


def test_dossier_contains_citations(settings) -> None:
    seed = parse_seed("Maria Silva Souza")
    assert seed
    with session_scope() as session:
        inv = create_investigation(
            session,
            title="Caso teste",
            hypothesis="Verificar menções",
            seeds=[seed],
            connectors=["wikidata"],
            max_depth=1,
            monitor=False,
            created_by="tester",
        )
        html = render_dossier_html(session, inv.id)
    assert "Caso teste" in html
    assert "Evidências" in html
    assert "fontes públicas" in html.lower() or "públicas" in html
