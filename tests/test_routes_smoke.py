import re

from fastapi.testclient import TestClient

from osint4all.api import create_app
from osint4all.db.session import session_scope
from osint4all.web.auth import seed_admin_user


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "csrf ausente"
    return match.group(1)


def test_consult_tools_assign_edit(settings) -> None:
    with session_scope() as session:
        seed_admin_user(session, settings)

    client = TestClient(create_app())
    token = _csrf(client.get("/login").text)
    logged = client.post(
        "/login",
        data={"username": "admin", "password": "secret", "csrf_token": token},
        follow_redirects=True,
    )
    assert logged.status_code == 200
    assert "scan_target" in logged.text.lower()

    token = _csrf(logged.text)
    plate = client.post("/app/consultar", data={"csrf_token": token, "q": "ABC1D23", "modo": "PLATE"})
    assert plate.status_code == 200
    assert "ABC1D23" in plate.text
    assert "Adicionar ao caso" not in plate.text
    assert "Novo caso" in plate.text

    tools = client.get("/app/ferramentas")
    assert tools.status_code == 200
    assert "Redes sociais" in tools.text
    assert "Busca em massa" in tools.text
    assert "github.com" not in tools.text.lower()

    token = _csrf(tools.text)
    created = client.post(
        "/app/nova",
        data={
            "csrf_token": token,
            "title": "Caso corrente",
            "hypothesis": "Teste de atribuição",
            "seed_plate": "ABC1D23",
            "max_depth": "1",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "Caso corrente" in created.text
    assert "Editar" in created.text
    assert "Buscar" in created.text

    token = _csrf(created.text)
    edited = client.post(
        f"/app/casos/{created.url.path.split('/')[3]}/editar",
        data={"csrf_token": token, "title": "Caso editado", "hypothesis": "Nova", "max_depth": "2"},
        follow_redirects=True,
    )
    assert edited.status_code == 200
    assert "Caso editado" in edited.text

    token = _csrf(edited.text)
    assigned = client.post(
        "/app/consultar/atribuir",
        data={
            "csrf_token": token,
            "kind": "PHONE",
            "value": "11987654321",
            "investigation_id": created.url.path.split("/")[3],
        },
        follow_redirects=True,
    )
    assert assigned.status_code == 200
    assert "adicionados" in assigned.text.lower() or "Caso editado" in assigned.text
