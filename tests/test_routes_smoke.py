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
    assert "Colar texto e extrair" in logged.text
    assert "mesa-tabs" in logged.text
    assert "Radar" in logged.text
    assert "Alertas" in logged.text
    assert 'href="/app/buscar"' in logged.text
    assert 'id="global-q"' in logged.text
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
    assert "Processos" in logged.text

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
    assert "Processos" in tools.text
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
    assert "pill" in body
    assert "Caso corrente" in created.text
    assert "Fila de identidade" in created.text
    assert "Revisar" in created.text
    assert "Descartado" in created.text
    assert "Provável" in created.text
    graph_json = client.get(f"/app/casos/{case_id}/grafo.json")
    assert graph_json.status_code == 200
    node_id = next((n["id"] for n in graph_json.json().get("nodes") or [] if n.get("id")), None)
    assert node_id
    ficha = client.get(f"/app/casos/{case_id}/entidades/{node_id}")
    assert ficha.status_code == 200
    assert "Por que este score" in ficha.text
    assert "Identidade" in ficha.text
    assert "Fonte" in ficha.text
    assert "Afirmação" in ficha.text
    assert "criado" in created.text.lower()
    assert "Editar" in created.text
    assert "Buscar" in created.text
    assert "Pesquisar tudo" in created.text
    assert "Ordenar" in created.text
    assert 'data-view="ordenar"' in created.text
    assert "pesquisar-tudo" in created.text
    assert "graph-year-min" in created.text
    assert "Explodir QSA" in created.text
    assert "Fila das fontes" in created.text
    investigar = client.get(f"/app/casos/{created.url.path.split('/')[3]}/investigar")
    assert investigar.status_code == 200
    assert "Rodar este passo" in investigar.text
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

    mesa_alvo = client.get("/app?mesa=alvo")
    assert mesa_alvo.status_code == 200
    assert "desta pessoa" in mesa_alvo.text.lower()
    assert "Buscar nesta camada" in mesa_alvo.text
    alerts = client.get("/app/alertas")
    assert alerts.status_code == 200
    assert "O que mudou" in alerts.text
    alvo = client.get("/app/alvo")
    assert alvo.status_code == 200
    assert "desta pessoa" in alvo.text.lower()
    assert "Buscar nesta camada" in alvo.text
    assert "Buscar preenchidas" in alvo.text
    assert "Colar texto e preencher" in alvo.text
    assert "Novo alvo" in alvo.text
    assert "Atribuir ao caso" in alvo.text

    token = _csrf(alvo.text)
    extracted = client.post(
        "/app/extrair",
        data={
            "csrf_token": token,
            "blob": "CPF 529.982.247-25 e-mail ana@exemplo.com placa ABC1D23 @jornalista",
        },
    )
    assert extracted.status_code == 200
    assert "identificador" in extracted.text.lower()
    assert "529.982.247-25" in extracted.text
    assert "ana@exemplo.com" in extracted.text
    assert "Mandar ao alvo" in extracted.text

    lookup = client.get("/app/buscar", params={"q": "ABC1D23"})
    assert lookup.status_code == 200
    assert "Onde já vi isto" in lookup.text
    assert "ABC1D23" in lookup.text or "ABC-1D23" in lookup.text

    token = _csrf(logged.text)
    blob_consult = client.post(
        "/app/consultar",
        data={
            "csrf_token": token,
            "q": "CPF 529.982.247-25\nCNPJ 33.000.167/0001-01\nana@exemplo.com",
            "modo": "auto",
        },
    )
    assert blob_consult.status_code == 200
    assert "texto colado" in blob_consult.text.lower()
    assert "Mandar ao alvo" in blob_consult.text

    midia = client.get(f"/app/casos/{created.url.path.split('/')[3]}/midia")
    assert midia.status_code == 200
    assert "CPF" in midia.text or "notícia" in midia.text.lower() or "menção" in midia.text.lower()
    assert "Adicionar selecionadas" in midia.text
    assert 'name="news_pick"' in midia.text or "marque" in midia.text.lower()

    alvo_media = client.get("/app/alvo/midia")
    assert alvo_media.status_code == 200
    assert "Adicionar selecionadas" in alvo_media.text

    manual = client.get("/app/manual")
    assert manual.status_code == 200
    assert "Manual da plataforma" in manual.text
    assert 'href="/app/manual"' in manual.text
    assert "Explodir QSA" in manual.text
    assert "Detectar" in manual.text
    assert "Cinco motores" in manual.text
    assert "Investigar" in manual.text
    assert "Resolução de identidade" in manual.text
    assert "Playbooks" in manual.text
    assert "/api/v1" in manual.text

    case_id = created.url.path.split("/")[3]
    exported = client.get(f"/app/casos/{case_id}/export.json")
    assert exported.status_code == 200
    assert exported.json().get("title")
    assert "citations" in exported.json()
    cases = client.get("/app/casos")
    assert "Arquivar" in cases.text
    token = _csrf(cases.text)
    archived = client.post(f"/app/casos/{case_id}/arquivar", data={"csrf_token": token}, follow_redirects=True)
    assert archived.status_code == 200
    assert "Nada guardado ainda" in client.get("/app/casos").text
    assert "Caso editado" in client.get("/app/casos?arquivo=1").text
    token = _csrf(client.get("/app/casos?arquivo=1").text)
    client.post(f"/app/casos/{case_id}/arquivar", data={"csrf_token": token, "restore": "1"}, follow_redirects=True)
    token = _csrf(client.get("/app/casos").text)
    purged = client.post(f"/app/casos/{case_id}/apagar", data={"csrf_token": token}, follow_redirects=True)
    assert purged.status_code == 200
    assert "caso apagado" in purged.text.lower()
    assert "Caso editado" not in purged.text
    leftover = client.get("/app/casos")
    assert leftover.status_code == 200
    assert "Caso editado" not in leftover.text
    assert case_id not in leftover.text
