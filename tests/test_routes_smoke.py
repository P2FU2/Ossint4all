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
    fontes = client.get("/app/admin")
    assert fontes.status_code == 200
    assert "Diários oficiais" in fontes.text
    assert "RDAP" in fontes.text
    assert "Shodan" in fontes.text
    assert "Nuclei" in fontes.text
    assert "theHarvester" in fontes.text
    assert "Maigret" in fontes.text
    assert "Aleph" in fontes.text
    assert "PhoneInfoga" in fontes.text
    assert "ExifTool" in fontes.text
    assert "E-mail · serviços públicos" in fontes.text
    assert "Ficha de host" in fontes.text
    assert "IVRE" in fontes.text
    assert "Dispara em" in fontes.text
    assert "Negativa" in logged.text
    assert "Imóvel" in logged.text
    assert "Diário" in logged.text
    assert "Processo" in logged.text

    token = _csrf(logged.text)
    mass = client.post("/app/consultar", data={"csrf_token": token, "q": "ABC1D23", "modo": "massa"})
    assert mass.status_code == 200
    assert "Busca em massa" in mass.text
    assert "ABC1D23" in mass.text
    assert "result-banner error" not in mass.text

    token = _csrf(logged.text)
    plate = client.post("/app/consultar", data={"csrf_token": token, "q": "ABC1D23", "modo": "PLATE"})
    assert plate.status_code == 200
    assert "ABC1D23" in plate.text
    assert "Adicionar ao caso" not in plate.text
    assert "Novo caso" in plate.text
    assert 'target="_blank"' not in plate.text
    assert "inspect-open" in plate.text
    assert "inspect-modal" in plate.text
    assert "search-history" in plate.text
    assert "histórico" in plate.text.lower()
    assert 'class="history-item' in plate.text

    token = _csrf(plate.text)
    cleared = client.post("/app/historico/limpar", data={"csrf_token": token}, follow_redirects=True)
    assert cleared.status_code == 200
    assert "nenhuma consulta" in cleared.text.lower()
    assert 'class="history-item' not in cleared.text

    token = _csrf(cleared.text)
    social = client.post("/app/consultar", data={"csrf_token": token, "q": "@ana", "modo": "USERNAME"})
    assert social.status_code == 200
    assert "última consulta" in social.text.lower()

    token = _csrf(social.text)
    email = client.post("/app/consultar", data={"csrf_token": token, "q": "ana@exemplo.com", "modo": "EMAIL"})
    assert email.status_code == 200
    assert "consultas ligadas" not in email.text.lower()
    assert "ana@exemplo.com" in email.text

    tools = client.get("/app/ferramentas")
    assert tools.status_code == 200
    assert "Redes sociais" in tools.text
    assert "Busca em massa" in tools.text
    assert "github.com" not in tools.text.lower()
    assert "search-history" in tools.text

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
    case_id = created.url.path.split("/")[3]
    pulse = client.get(f"/app/casos/{case_id}/status")
    assert pulse.status_code == 200
    body = pulse.json()
    assert "entities" in body
    assert "PENDING" in body
    assert "label" in body
    assert "Caso corrente" in created.text
    assert "criado" in created.text.lower()
    assert "Editar" in created.text
    assert "Buscar" in created.text
    assert "Explodir QSA" in created.text
    assert "Buscar e acrescentar" in created.text
    assert "buscar-ferramentas" in created.text
    assert "canvas-tools" in created.text
    assert "ct-dots" in created.text

    token = _csrf(created.text)
    edited = client.post(
        f"/app/casos/{created.url.path.split('/')[3]}/editar",
        data={
            "csrf_token": token,
            "title": "Caso editado",
            "hypothesis": "Nova",
            "max_depth": "2",
            "seed_email": "alvo@exemplo.com",
        },
        follow_redirects=True,
    )
    assert edited.status_code == 200
    assert "Caso editado" in edited.text
    assert "atualizado" in edited.text.lower()
    assert "identificador" in edited.text.lower()
    assert "alvo@exemplo.com" in edited.text or "já no grafo" in edited.text.lower()

    token = _csrf(edited.text)
    tools_run = client.post(
        f"/app/casos/{created.url.path.split('/')[3]}/buscar-ferramentas",
        data={"csrf_token": token, "tools": "plate"},
        follow_redirects=True,
    )
    assert tools_run.status_code == 200
    assert "complementar" in tools_run.text.lower() or "acrescent" in tools_run.text.lower() or "Caso editado" in tools_run.text

    token = _csrf(tools_run.text)
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

    alvo = client.get("/app/alvo")
    assert alvo.status_code == 200
    assert "desta pessoa" in alvo.text.lower()
    assert "Buscar nesta camada" in alvo.text
    assert "Novo alvo" in alvo.text
    assert "Atribuir ao caso" in alvo.text

    midia = client.get(f"/app/casos/{created.url.path.split('/')[3]}/midia")
    assert midia.status_code == 200
    assert "CPF" in midia.text or "notícia" in midia.text.lower() or "menção" in midia.text.lower()

    alvo_media = client.get("/app/alvo/midia")
    assert alvo_media.status_code == 200

    manual = client.get("/app/manual")
    assert manual.status_code == 200
    assert "Manual da plataforma" in manual.text
    assert 'href="/app/manual"' in manual.text
    assert "Explodir QSA" in manual.text
    assert "Detectar" in manual.text
    assert "Cinco motores" in manual.text
    assert "Investigar" in manual.text
    assert "Playbooks" in manual.text
    assert "/api/v1" in manual.text

    case_id = created.url.path.split("/")[3]
    token = _csrf(client.get("/app/casos").text)
    purged = client.post(f"/app/casos/{case_id}/apagar", data={"csrf_token": token}, follow_redirects=True)
    assert purged.status_code == 200
    assert "caso apagado" in purged.text.lower()
    assert "Caso editado" not in purged.text
    leftover = client.get("/app/casos")
    assert leftover.status_code == 200
    assert "Caso editado" not in leftover.text
    assert case_id not in leftover.text
