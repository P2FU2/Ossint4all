from osint4all.connectors.socio_search import extract_cnpjs, parse_socio_hits
from osint4all.connectors.plate_public import (
    extract_owner_mentions,
    extract_vehicle_card,
    extract_vehicle_mentions,
    parse_plate_enrichment,
    uf_from_plate_series,
)
from osint4all.connectors.crtsh import parse_crtsh_rows
from osint4all.connectors.opencorporates import parse_opencorporates
from osint4all.connectors.transparencia import parse_transparencia_rows
from osint4all.connectors.tse import parse_tse_candidates
from osint4all.connectors.username_public import parse_public_hits
from osint4all.connectors.web_search import parse_searxng_payload, parse_web_hits, searxng_bases, web_search_ready
from osint4all.config import Settings
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


def test_vehicle_card_from_listing() -> None:
    card = extract_vehicle_card("Leilão: VW GOL 1.0 2018 prata placa ABC1D23")
    assert card.get("marca") == "Volkswagen"
    assert "Gol" in (card.get("modelo") or "")
    assert card.get("ano") == "2018"
    assert extract_vehicle_mentions("Honda Civic 2018 em nome de Ana") == ["Honda Civic 2018"]
    labeled = extract_vehicle_card("Marca: Fiat Modelo: Strada Ano: 2021 Cor: branco")
    assert labeled["marca"] == "Fiat"
    assert labeled["modelo"] == "Strada"
    assert labeled["ano"] == "2021"


def test_plate_enrichment_and_owner() -> None:
    assert uf_from_plate_series("BFA1A23") == "SP"
    assert uf_from_plate_series("AAA1A11") == "PR"
    assert extract_owner_mentions("Veículo em nome de Maria Silva Souza, placa ABC-1D23") == ["Maria Silva Souza"]
    result = parse_plate_enrichment(
        "ABC1D23",
        origin_key="plate:ABC1D23",
        owner_name="Joao da Silva",
        owner_cpf="529.982.247-25",
    )
    assert any(e.entity_type == "VEHICLE" for e in result.entities)
    assert any(e.entity_type == "PERSON" for e in result.entities)
    assert any(e.rel_type == "PROPRIETARIO" for e in result.edges)
    assert result.evidence


def test_socio_search_hits() -> None:
    assert extract_cnpjs("empresa 07.810.004/0001-84 e outra") == ["07810004000184"]
    result = parse_socio_hits(
        [
            {
                "cnpj": "07.810.004/0001-84",
                "razao_social": "MMONOECO AGB",
                "municipio": "GARUVA",
                "uf": "SC",
                "situacao_cadastral": "ATIVA",
            }
        ],
        origin_key="name:theofilos rifiotis",
        source_label="teste",
    )
    assert any(e.entity_type == "ORG" for e in result.entities)
    assert any(e.rel_type == "SOCIO" for e in result.edges)


def test_web_hits_extract_plate_owner() -> None:
    web = parse_web_hits(
        [
            {
                "url": "https://exemplo.com/noticia",
                "title": "Acidente",
                "snippet": "O Honda Civic 2018 em nome de Ana Paula Costa foi apreendido.",
            }
        ],
        origin_key="plate:ABC1D23",
    )
    assert any(e.rel_type == "PROPRIETARIO" for e in web.edges)
    assert any(e.entity_type == "PERSON" for e in web.entities)


def test_searxng_payload_and_ready() -> None:
    parsed = parse_searxng_payload(
        {
            "results": [
                {
                    "url": "https://exemplo.org/ficha",
                    "title": "Ficha pública",
                    "content": "menção ao alvo",
                    "engine": "google",
                }
            ]
        },
        origin_key="email:ana@exemplo.com",
        instance="https://priv.au",
    )
    assert parsed.entities[0].entity_type == "PUBLICATION"
    assert "SearXNG" in parsed.evidence[0].source_label
    settings = Settings(searxng_enable=True, searxng_url="https://searx.local")
    assert web_search_ready(settings)
    bases = searxng_bases(settings)
    assert bases[0] == "https://searx.local"
    assert "https://priv.au" in bases
    assert not web_search_ready(Settings(web_search_enable=False))
