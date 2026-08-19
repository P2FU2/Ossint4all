from osint4all.connectors.crtsh import parse_crtsh_rows
from osint4all.connectors.opencorporates import parse_opencorporates
from osint4all.connectors.transparencia import parse_transparencia_rows
from osint4all.connectors.tse import parse_tse_candidates
from osint4all.connectors.username_public import parse_public_hits
from osint4all.connectors.web_search import parse_web_hits
from osint4all.connectors.wikidata import parse_wikidata_search


def test_tse_candidates() -> None:
    result = parse_tse_candidates(
        [{"nomeUrna": "MARIA SILVA", "cargo": {"nome": "Prefeito"}, "partido": {"sigla": "PX"}, "uf": "SP"}],
        origin_key="name:outra pessoa",
    )
    assert any(e.rel_type == "CANDIDATO" for e in result.edges)
    assert result.evidence


def test_transparencia_ceis() -> None:
    result = parse_transparencia_rows(
        [{"nome": "Empresa X", "cpfCnpj": "33000167000101", "orgao": "CGU"}],
        origin_key="cpf:52998224725",
        lista="CEIS",
    )
    assert any(e.entity_type == "ORG" for e in result.entities)


def test_opencorporates_and_web_and_wiki() -> None:
    oc = parse_opencorporates(
        [{"company": {"name": "ACME LTD", "company_number": "123", "jurisdiction_code": "gb", "opencorporates_url": "https://opencorporates.com/c"}}],
        origin_key="name:acme",
    )
    assert oc.entities
    web = parse_web_hits(
        [{"url": "https://example.com/a", "title": "Materia", "snippet": "texto"}],
        origin_key="name:maria",
    )
    assert web.entities[0].entity_type == "PUBLICATION"
    wiki = parse_wikidata_search(
        [{"id": "Q1", "label": "Universo", "description": "tudo"}],
        origin_key="name:universo",
    )
    assert wiki.evidence[0].url.endswith("Q1")


def test_username_public_hits() -> None:
    result = parse_public_hits([("GitHub", "https://github.com/alice")], origin_key="username:alice")
    assert result.entities[0].entity_type == "PROFILE"


def test_crtsh_names() -> None:
    result = parse_crtsh_rows(
        [
            {"name_value": "www.exemplo.gov.br\nexemplo.gov.br", "id": 1, "issuer_name": "Let's Encrypt"},
            {"common_name": "cdn.exemplo.gov.br", "id": 2},
        ],
        origin_key="url:https://exemplo.gov.br",
        domain="exemplo.gov.br",
    )
    names = {e.display_name for e in result.entities}
    assert "exemplo.gov.br" in names
    assert result.evidence
