from osint4all.connectors.cnpj_receita import parse_cnpj_payload
from osint4all.connectors.congresso_public import parse_deputados, parse_senadores
from osint4all.connectors.politicos_public import official_photo_attrs, parse_pep_rows, parse_ranking_hits, parse_ranking_html
from osint4all.connectors.gleif_public import parse_gleif_records
from osint4all.connectors.opensanctions_public import parse_opensanctions_hits
from osint4all.connectors.pncp_public import parse_pncp_items
from osint4all.connectors.tse import TseConnector, parse_tse_assets, parse_tse_donations
from osint4all.connectors.web_search import classify_public_mention, parse_web_hits
from osint4all.engines.intelligence import compare_entities
from osint4all.engines.playbooks import CASE_STEPS, DOMAIN_STEPS, attach_playbook, infer_playbook, list_items
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import canonical_key, parse_seed
from osint4all.report.graphml import render_graphml
from osint4all.validators import cnpj_matriz, compose_cnpj, is_cnpj_filial, validate_cnpj


def test_classify_public_mention_types() -> None:
    assert classify_public_mention("DOU", "publicado no diário oficial", "https://www.in.gov.br/x") == "diario"
    assert classify_public_mention("Hasta", "leilão de imóvel da Caixa", "https://exemplo.com/a") == "imovel"
    assert classify_public_mention("Edital", "contrato no PNCP", "https://pncp.gov.br/x") == "contrato"
    assert classify_public_mention("Nota", "entrevista", "https://exemplo.com/n") == "mencao"


def test_web_hits_type_imovel_and_diario() -> None:
    web = parse_web_hits(
        [
            {"url": "https://www.in.gov.br/materia", "title": "Atos", "snippet": "Diário Oficial da União"},
            {"url": "https://venda-imoveis.caixa.gov.br/x", "title": "Leilão", "snippet": "hasta pública de imóvel"},
        ],
        origin_key="name:maria silva",
    )
    tipos = {e.attrs.get("tipo") for e in web.entities}
    assert "diario" in tipos
    assert "imovel" in tipos
    assert any(e.entity_type == "ASSET" for e in web.entities)
    assert any(e.rel_type == "PATRIMONIO" for e in web.edges)


def test_pncp_and_gleif_and_sanctions_parsers() -> None:
    pncp = parse_pncp_items(
        [
            {
                "titulo": "Fornecimento de combustível",
                "orgao_nome": "Prefeitura",
                "orgao_cnpj": "00000000000191",
                "valor": 1000,
                "item_url": "https://pncp.gov.br/app/contratos/1",
            }
        ],
        origin_key="cnpj:33000167000101",
    )
    assert any(e.rel_type == "CONTRATO" for e in pncp.edges)
    assert pncp.evidence

    sanctions = parse_opensanctions_hits(
        [{"id": "NK-1", "caption": "Example Person", "schema": "Person", "datasets": ["us_ofac"], "properties": {"topics": ["sanction"]}}],
        origin_key="name:example person",
    )
    assert sanctions.entities[0].attrs["tipo"] == "sancao"
    assert sanctions.edges[0].rel_type == "SANCAO"

    gleif = parse_gleif_records(
        [
            {
                "id": "25490011111111111111",
                "attributes": {
                    "lei": "25490011111111111111",
                    "entity": {"legalName": {"name": "PETROBRAS"}, "registeredAs": "33000167000101", "jurisdiction": "BR"},
                },
            }
        ],
        origin_key="cnpj:33000167000101",
    )
    assert gleif.entities
    assert gleif.evidence[0].payload["lei"] == "25490011111111111111"


def test_pep_ranking_and_official_photo() -> None:
    pep = parse_pep_rows(
        [
            {"nome": "Maria Silva Souza", "descricaoFuncao": "Deputada", "nomeOrgao": "Câmara"},
            {"nome": "João Outro", "descricaoFuncao": "Senador"},
        ],
        origin_key="name:maria silva souza",
        needle="Maria Silva Souza",
    )
    assert any(e.display_name == "Maria Silva Souza" for e in pep.entities)
    assert all("João" not in (e.display_name or "") for e in pep.entities)
    rank = parse_ranking_hits(
        [{"nome": "Maria Silva Souza", "url": "https://ranking.org.br/politicos/maria", "snippet": "nota 7"}],
        origin_key="name:maria silva souza",
        needle="Maria Silva Souza",
    )
    assert rank.entities[0].kind == "URL"
    photo = official_photo_attrs(
        {"urlFoto": "https://www.camara.leg.br/internet/deputado/bandep/1.jpg"},
        needle="Maria Silva Souza",
        nome="Maria Silva Souza",
    )
    assert photo["thumb"].startswith("https://")
    assert photo["identity_match"] >= 50


def test_camara_rejects_homonym_below_overlap() -> None:
    deps = parse_deputados(
        [{"id": 2, "nome": "Lula da Fonte", "siglaPartido": "PP", "siglaUf": "PE", "urlFoto": "https://www.camara.leg.br/foto.jpg"}],
        origin_key="name:luiz inacio lula da silva",
        needle="Luiz Inácio Lula da Silva",
    )
    assert not any(e.entity_type == "PERSON" for e in deps.entities)


def test_ranking_html_picks_politician_path() -> None:
    items = parse_ranking_html(
        '<a href="/politicos/maria-silva-souza">Maria Silva Souza — nota 7</a>',
        nome="Maria Silva Souza",
    )
    assert items
    assert "politicos" in items[0]["url"]


def test_web_search_empty_backends_return_notes(settings, monkeypatch) -> None:
    from osint4all.connectors.web_search import WebSearchConnector

    monkeypatch.setattr(settings, "brave_search_api_key", "")
    monkeypatch.setattr(settings, "google_cse_api_key", "")
    monkeypatch.setattr(settings, "google_cse_cx", "")
    monkeypatch.setattr(settings, "searxng_enable", False)
    conn = WebSearchConnector(settings)
    from osint4all.connectors.base import ConnectorResult

    conn._duckduckgo = lambda *a, **k: ConnectorResult(notes=["ddg off"])
    result = conn.search("Maria Silva Souza", "name:maria silva souza")
    assert result.entities == []
    assert result.notes


def test_tse_forbidden_returns_notes_not_exception(settings) -> None:
    class FakeResp:
        status_code = 403

        def json(self):
            return {}

    conn = TseConnector(settings)
    conn.http.request = lambda *a, **k: FakeResp()
    from types import SimpleNamespace

    from osint4all.connectors.base import ExpandContext

    entity = SimpleNamespace(display_name="Maria Silva Souza", canonical_key="name:maria silva souza")
    result = conn.collect(entity, ExpandContext(investigation=None, settings=settings, enabled=set()))
    assert any("403" in note for note in result.notes)
    assert result.evidence


def test_congresso_and_tse_assets() -> None:
    deps = parse_deputados(
        [{"id": 1, "nome": "Maria Silva Souza", "siglaPartido": "PX", "siglaUf": "SP", "uri": "https://www.camara.leg.br/deputados/1", "urlFoto": "https://www.camara.leg.br/foto.jpg"}],
        origin_key="name:outra",
        needle="Maria Silva",
    )
    assert any(e.entity_type == "PERSON" for e in deps.entities)
    assert any((e.attrs or {}).get("thumb") for e in deps.entities)
    senate = parse_senadores(
        {"ListaParlamentarEmExercicio": {"Parlamentares": {"Parlamentar": [{"IdentificacaoParlamentar": {"NomeParlamentar": "Maria Silva Souza", "SiglaPartidoParlamentar": "PX", "UfParlamentar": "SP", "CodigoParlamentar": "9"}}]}}},
        origin_key="name:outra",
        needle="Maria Silva",
    )
    assert senate.evidence
    bens = parse_tse_assets(
        [{"descricaoTipoBem": "Imóvel", "descricaoDeBem": "Casa em Brasília", "valor": 500000}],
        origin_key="name:maria silva",
        owner_name="Maria Silva",
    )
    assert bens.entities[0].entity_type == "ASSET"
    assert bens.edges[0].rel_type == "TITULAR"
    doa = parse_tse_donations(
        [{"nomeDoador": "Empresa X", "cpfCnpjDoador": "00000000000191", "valor": 2000}],
        origin_key="name:maria silva",
    )
    assert any(e.rel_type == "DOACAO" for e in doa.edges)


def test_cnpj_filial_and_contacts() -> None:
    matriz = "33000167000101"
    filial = compose_cnpj(matriz[:8] + "0002")
    assert filial and validate_cnpj(filial)
    assert is_cnpj_filial(filial)
    assert cnpj_matriz(filial) == matriz
    result = parse_cnpj_payload(
        {
            "cnpj": filial,
            "razao_social": "PETRO FILIAL",
            "ddd_telefone_1": "2132212000",
            "correio_eletronico": "contato@petro.example",
            "cnaes_secundarios": [{"descricao": "Apoio"}],
            "qsa": [],
        }
    )
    org = next(e for e in result.entities if e.kind == "CNPJ" and e.value == filial)
    assert org.attrs["matriz_filial"] == "filial"
    assert org.attrs["cnpj_raiz"] == "33000167"
    assert any(e.kind == "EMAIL" for e in result.entities)
    assert any(e.rel_type == "FILIAL" for e in result.edges)
    assert any(e.to_ref == canonical_key("CNPJ", matriz) for e in result.edges)


def test_playbook_case_and_domain(db) -> None:
    seed = parse_seed("0000123-45.2024.8.26.0100")
    inv = create_investigation(
        db, title="Processo", hypothesis="Capa", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    assert inv.playbook_key == "CASE"
    assert len(list_items(db, inv.id)) == len(CASE_STEPS)
    domain = parse_seed("https://empresa.example")
    other = create_investigation(
        db, title="Site", hypothesis="Domínio", seeds=[domain], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    assert other.playbook_key == "DOMAIN"
    assert len(list_items(db, other.id)) == len(DOMAIN_STEPS)
    attach_playbook(db, other, "DOMAIN")
    assert infer_playbook(other) == "DOMAIN"


def test_compare_and_graphml(db) -> None:
    left = parse_seed("33.000.167/0001-01")
    right = parse_seed("Joao da Silva Souza")
    inv = create_investigation(
        db, title="Cruza", hypothesis="QSA", seeds=[left, right], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    people = [e for e in inv.entities]
    compared = compare_entities(db, inv.id, people[0].id, people[-1].id)
    assert compared["ok"] is True
    xml = render_graphml(db, inv.id)
    assert "<graphml" in xml
    assert people[0].id in xml
