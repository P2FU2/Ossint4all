from osint4all.config import Settings
from osint4all.connectors.socio_search import (
    SocioSearchConnector,
    confirm_company_rows,
    cpf_from_entity,
    extract_cnpjs,
    parse_socio_hits,
    partner_link_verdict,
)
from osint4all.connectors.plate_public import (
    extract_owner_mentions,
    extract_vehicle_card,
    extract_vehicle_mentions,
    parse_plate_enrichment,
    uf_from_plate_series,
)
from osint4all.connectors.crtsh import parse_crtsh_rows
from osint4all.connectors.opencorporates import parse_opencorporates
from osint4all.connectors.transparencia import parse_transparencia_rows, transparencia_params
from osint4all.connectors.tse import parse_tse_candidates, tse_candidate_match
from osint4all.connectors.username_public import (
    is_reserved_username,
    parse_public_hits,
    username_from_entity,
)
from osint4all.connectors.web_search import parse_searxng_payload, parse_web_hits, searxng_bases, web_search_ready
from osint4all.connectors.wikidata import commons_file_url, parse_wikidata_entity, parse_wikidata_search


def test_tse_candidates() -> None:
    result = parse_tse_candidates(
        [{"nomeUrna": "MARIA SILVA", "cargo": {"nome": "Prefeito"}, "partido": {"sigla": "PX"}, "uf": "SP"}],
        origin_key="name:outra pessoa",
    )
    assert any(e.rel_type == "CANDIDATO" for e in result.edges)
    assert result.evidence


def test_tse_matches_urna_not_full_string() -> None:
    assert tse_candidate_match({"nomeUrna": "LULA", "nomeCompleto": "LUIZ INACIO LULA DA SILVA"}, "Luiz Inácio Lula da Silva")
    assert not tse_candidate_match({"nomeUrna": "LULA DA FONTE", "nomeCompleto": "LULA DA FONTE"}, "Luiz Inácio Lula da Silva")
    assert not tse_candidate_match({"nomeUrna": "SILVA"}, "Luiz Inácio Lula da Silva")


def test_transparencia_params_per_list() -> None:
    assert transparencia_params("CEIS", "52998224725") == {"codigoSancionado": "52998224725", "pagina": 1}
    assert transparencia_params("CEAF", "52998224725") == {"cpfSancionado": "52998224725", "pagina": 1}
    assert transparencia_params("CEAF", "33000167000101") is None
    assert transparencia_params("CEPIM", "33000167000101") == {"cnpjSancionado": "33000167000101", "pagina": 1}
    assert transparencia_params("PEP", "52998224725") == {"cpf": "52998224725", "pagina": 1}


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
    assert commons_file_url("File:Foto teste.jpg").startswith("https://commons.wikimedia.org/")
    entity = parse_wikidata_entity(
        {
            "entities": {
                "Q87": {
                    "labels": {"pt": {"value": "Maria Silva Souza"}},
                    "claims": {
                        "P18": [{"mainsnak": {"datavalue": {"value": "Maria.jpg"}}}],
                        "P569": [{"mainsnak": {"datavalue": {"value": {"time": "+1970-01-02T00:00:00Z"}}}}],
                    },
                    "sitelinks": {"ptwiki": {"title": "Maria Silva Souza"}},
                }
            }
        },
        origin_key="name:maria silva souza",
        needle="Maria Silva Souza",
    )
    assert any((e.attrs or {}).get("profile_photo") for e in entity.entities)
    assert any(e.entity_type == "PUBLICATION" for e in entity.entities)


def test_free_html_parsers() -> None:
    from osint4all.connectors.html_public import parse_ddg_html, parse_opensanctions_html, parse_portal_payload

    ddg = parse_ddg_html(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexemplo.gov.br%2Fx">Portal público</a>'
    )
    assert ddg
    assert ddg[0]["url"].startswith("https://exemplo.gov.br")
    osanc = parse_opensanctions_html(
        '<a href="/entities/br-pep-1">Maria Silva Souza</a>',
        origin_key="name:maria silva souza",
    )
    assert osanc.entities
    portal = parse_portal_payload(
        {"data": [{"nome": "Empresa X", "cpfCnpj": "33000167000101", "orgao": "CGU"}]},
        origin_key="cnpj:33000167000101",
        lista="CEIS",
    )
    assert portal.entities


def test_username_public_hits() -> None:
    result = parse_public_hits([("GitHub", "https://github.com/alice")], origin_key="username:alice", user="alice")
    assert result.entities[0].entity_type == "PROFILE"
    assert "@alice" in result.entities[0].display_name
    assert result.entities[0].attrs["thumb"] == "https://github.com/alice.png?size=240"


def test_username_rejects_platform_brand_overlap() -> None:
    assert is_reserved_username("telegram")
    assert is_reserved_username("pinterest")
    assert is_reserved_username("vimeo")
    assert not is_reserved_username("alice")
    brand = parse_public_hits(
        [("Vimeo", "https://vimeo.com/telegram"), ("Linktree", "https://linktr.ee/pinterest")],
        origin_key="username:telegram",
        user="telegram",
    )
    assert brand.entities == []
    assert brand.edges == []
    profile = type("E", (), {"canonical_key": "url:https://vimeo.com/telegram", "display_name": "Vimeo", "entity_type": "PROFILE", "identifiers": []})()
    assert username_from_entity(profile) is None
    handle = type("E", (), {"canonical_key": "username:alice", "display_name": "Telegram", "entity_type": "PERSON", "identifiers": []})()
    assert username_from_entity(handle) == "alice"


def test_socio_search_reads_cpf_anchor() -> None:
    person = type(
        "E",
        (),
        {"canonical_key": "cpf:52998224725", "display_name": "Ana", "entity_type": "PERSON", "identifiers": []},
    )()
    assert cpf_from_entity(person) == "52998224725"
    fake = type(
        "E",
        (),
        {"canonical_key": "cpf:11111111111", "display_name": "X", "entity_type": "PERSON", "identifiers": []},
    )()
    assert cpf_from_entity(fake) is None
    named = type(
        "E",
        (),
        {"canonical_key": "name:ana silva souza", "display_name": "Ana Silva Souza", "entity_type": "PERSON", "identifiers": []},
    )()
    assert cpf_from_entity(named) is None


def test_company_confirms_by_cpf_in_qsa() -> None:
    from osint4all.connectors.base import ConnectorResult, FoundEntity

    parsed = ConnectorResult(
        entities=[
            FoundEntity(entity_type="ORG", kind="CNPJ", value="07810004000184", display_name="X"),
            FoundEntity(entity_type="PERSON", kind="CPF", value="52998224725", display_name="ANA"),
        ]
    )
    assert partner_link_verdict(parsed, name="Outro Nome Completo", cpf="52998224725") == "cpf"
    rows = [{"cnpj": "07.810.004/0001-84", "razao_social": "X"}]
    payloads = {
        "07810004000184": {
            "cnpj": "07810004000184",
            "razao_social": "X",
            "qsa": [{"nome_socio": "ANA", "cnpj_cpf_do_socio": "52998224725"}],
        }
    }
    kept = confirm_company_rows(rows, name="Outro Nome Completo", cpf="52998224725", payloads=payloads)
    assert len(kept) == 1
    assert kept[0][1] == "cpf"


def test_companies_probe_uses_name_when_cpf_index_empty() -> None:
    from osint4all.connectors.base import ConnectorResult, ExpandContext
    from osint4all.graph.identity import TargetProfile

    conn = SocioSearchConnector(Settings(brasil_io_api_token="", socio_search_enable=True))
    seen: dict[str, str] = {}

    def fake_casa(name, origin, *, name_only=True, cpf=""):
        seen["name"] = name
        seen["cpf"] = cpf
        seen["name_only"] = str(name_only)
        return ConnectorResult(notes=["casa"])

    conn._casadosdados = fake_casa  # type: ignore[method-assign]
    conn._web_mentions = lambda *a, **k: ConnectorResult()  # type: ignore[method-assign]
    person = type(
        "E",
        (),
        {
            "canonical_key": "cpf:52998224725",
            "display_name": "Eduardo Hermelino Leite",
            "entity_type": "PERSON",
            "identifiers": [],
            "attrs": {"probe_kinds": ["COMPANIES"]},
        },
    )()
    ctx = ExpandContext(
        investigation=None,  # type: ignore[arg-type]
        settings=Settings(),
        enabled={"socio_search"},
        profile=TargetProfile(name="Eduardo Hermelino Leite", cpf="52998224725"),
    )
    result = conn.collect(person, ctx)
    assert seen["name"] == "Eduardo Hermelino Leite"
    assert seen["cpf"] == "52998224725"
    assert seen["name_only"] == "False"
    assert any("casa" in note for note in result.notes)


def test_cpf_search_does_not_invent_companies() -> None:
    conn = SocioSearchConnector(Settings(brasil_io_api_token=""))
    empty = conn.collect_by_cpf("52998224725", "cpf:52998224725")
    assert empty.entities == []
    assert empty.edges == []
    assert any("Brasil.IO" in note for note in empty.notes)
    assert conn.collect_by_cpf("11111111111", "cpf:11111111111").entities == []


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


def test_company_needs_qsa_before_linking() -> None:
    from osint4all.connectors.base import ConnectorResult, FoundEntity

    parsed = ConnectorResult(
        entities=[
            FoundEntity(entity_type="ORG", kind="CNPJ", value="07810004000184", display_name="MMONOECO"),
            FoundEntity(entity_type="PERSON", kind="NAME", value="THEOFILOS RIFIOTIS", display_name="THEOFILOS RIFIOTIS"),
        ]
    )
    assert partner_link_verdict(parsed, name="Theofilos Rifiotis") == "name"
    assert partner_link_verdict(parsed, name="Pedro Milani Marinho Queiroz Neves") == ""
    rows = [
        {"cnpj": "07.810.004/0001-84", "razao_social": "MMONOECO AGB"},
        {"cnpj": "33.000.167/0001-01", "razao_social": "OUTRA"},
    ]
    payloads = {
        "07810004000184": {
            "cnpj": "07810004000184",
            "razao_social": "MMONOECO",
            "qsa": [{"nome_socio": "THEOFILOS RIFIOTIS", "qualificacao_socio": "Sócio"}],
        },
        "33000167000101": {
            "cnpj": "33000167000101",
            "razao_social": "PETRO",
            "qsa": [{"nome_socio": "OUTRA PESSOA", "qualificacao_socio": "Sócio"}],
        },
    }
    kept = confirm_company_rows(rows, name="Theofilos Rifiotis", payloads=payloads)
    assert len(kept) == 1
    assert kept[0][1] == "name"


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
