from osint4all.catalog.sources import SOURCE_CATALOG, source_cards
from osint4all.config import ALL_CONNECTORS
from osint4all.connectors.diario_oficial import parse_gazette_rows
from osint4all.connectors.geo_public import address_query, parse_nominatim_rows, parse_viacep
from osint4all.connectors.rdap_public import parse_rdap
from osint4all.connectors.registry import build_connectors, enabled_connector_names
from osint4all.catalog.opensource import OSS_TOOLS
from osint4all.connectors.aleph_public import parse_aleph_results
from osint4all.connectors.censys_public import parse_censys_hits
from osint4all.connectors.email_public import parse_gravatar_entry, parse_keybase_lookup
from osint4all.connectors.host_public import parse_hackertarget_text, parse_urlscan_results, parse_wayback_cdx
from osint4all.connectors.phone_public import describe_phone
from osint4all.connectors.shodan_public import parse_shodan_matches, query_from_entity


def test_catalog_covers_every_connector() -> None:
    assert set(SOURCE_CATALOG) == set(ALL_CONNECTORS)
    cards = source_cards()
    assert {card["id"] for card in cards} == set(ALL_CONNECTORS)
    assert all(card["how"] and card["accepts"] and card["returns"] for card in cards)


def test_new_connectors_are_wired(settings) -> None:
    names = {connector.name for connector in build_connectors(settings)}
    assert {"diario_oficial", "geo_public", "rdap_public", "shodan_public", "host_public", "email_public", "phone_public", "aleph_public", "censys_public", "host_observe", "google_public"} <= names
    enabled = enabled_connector_names(settings)
    assert "diario_oficial" in enabled
    assert "geo_public" in enabled
    assert "rdap_public" in enabled
    assert "shodan_public" in enabled
    assert "email_public" in enabled
    assert "phone_public" in enabled
    assert "aleph_public" in enabled
    assert "censys_public" in enabled
    assert "host_observe" in enabled
    assert "google_public" in enabled


def test_parse_gazette_rows() -> None:
    result = parse_gazette_rows(
        [
            {
                "territory_name": "Campinas",
                "state_code": "SP",
                "date": "2024-03-01",
                "url": "https://querido-diario.ok.org.br/x",
                "excerpt": "concorrência pública",
            },
            {"url": ""},
        ],
        origin_key="cnpj:33000167000101",
        query="33000167000101",
    )
    assert len(result.entities) == 1
    assert result.entities[0].entity_type == "PUBLICATION"
    assert result.edges[0].rel_type == "MENCAO"


def test_parse_geo_helpers() -> None:
    assert parse_viacep({"erro": True}) == {}
    via = parse_viacep({"localidade": "Santos", "uf": "SP", "bairro": "Centro", "logradouro": "Rua X"})
    assert via["municipio"] == "Santos"
    geo = parse_nominatim_rows([{"lat": "-23.96", "lon": "-46.33", "display_name": "Santos, SP"}])
    assert geo["lat"] == -23.96
    assert "Santos" in address_query({"municipio": "Santos", "uf": "SP"})


def test_parse_rdap_skips_empty_and_reads_vcard() -> None:
    empty = parse_rdap({}, origin_key="email:a@empresa.com.br", domain="empresa.com.br")
    assert empty.entities[0].display_name == "empresa.com.br"
    result = parse_rdap(
        {
            "ldhName": "empresa.com.br",
            "entities": [{"vcardArray": ["vcard", [["fn", {}, "text", "Maria Silva Souza"]]]}],
            "events": [{"eventAction": "registration", "eventDate": "2010-01-01"}],
        },
        origin_key="email:a@empresa.com.br",
        domain="empresa.com.br",
    )
    assert any(entity.kind == "NAME" and entity.display_name == "Maria Silva Souza" for entity in result.entities)
    assert any("registration" in ev.snippet for ev in result.evidence)


def test_parse_shodan_keeps_host_drops_vuln() -> None:
    from types import SimpleNamespace

    person = SimpleNamespace(entity_type="PERSON", display_name="Ana Silva", attrs={}, identifiers=[], canonical_key="name:ana")
    assert query_from_entity(person) is None
    org = SimpleNamespace(
        entity_type="ORG",
        display_name="Petrobras Distribuidora",
        attrs={"razao_social": "Petrobras Distribuidora"},
        identifiers=[],
        canonical_key="cnpj:33000167000101",
    )
    assert 'org:"Petrobras Distribuidora"' == query_from_entity(org)
    result = parse_shodan_matches(
        [
            {
                "ip_str": "203.0.113.10",
                "port": 443,
                "product": "nginx",
                "org": "Exemplo SA",
                "hostnames": ["www.exemplo.com.br"],
                "vulns": {"CVE-2021-34473": {}},
                "http": {"title": "Portal"},
                "location": {"city": "São Paulo", "country_name": "Brazil"},
            }
        ],
        origin_key="cnpj:33000167000101",
    )
    assert result.entities[0].display_name == "exemplo.com.br"
    assert "CVE" not in (result.evidence[0].snippet or "")
    assert "vulns" not in (result.evidence[0].payload or {})


def test_oss_catalog_marks_nuclei_out() -> None:
    by_name = {row["name"]: row["status"] for row in OSS_TOOLS}
    assert by_name["Nuclei"] == "parcial"
    assert by_name["httpx (ProjectDiscovery)"] == "parcial"
    assert by_name["ZMap"] == "fora"
    assert by_name["Masscan"] == "parcial"
    assert by_name["GHunt"] == "parcial"
    assert by_name["Photon"] == "parcial"
    assert by_name["IVRE"] == "parcial"
    assert by_name["ZGrab2"] == "parcial"
    assert by_name["Sherlock"] == "embutido"
    assert by_name["Maigret"] == "embutido"
    assert by_name["Aleph"] == "embutido"
    assert by_name["ExifTool"] == "embutido"
    assert by_name["theHarvester"] == "embutido"
    assert by_name["Holehe"] == "parcial"
    assert by_name["PhoneInfoga"] == "parcial"
    assert by_name["Uncover"] == "parcial"


def test_parse_host_indexes() -> None:
    ht = parse_hackertarget_text(
        "www.exemplo.com.br,203.0.113.10\nerror rate limit\nmail.exemplo.com.br,203.0.113.11\n",
        domain="exemplo.com.br",
        origin_key="url:https://exemplo.com.br",
    )
    hosts = {e.display_name for e in ht.entities}
    assert "exemplo.com.br" in hosts or "mail.exemplo.com.br" in hosts
    wb = parse_wayback_cdx(
        [["original"], ["http://blog.exemplo.com.br/x"]],
        domain="exemplo.com.br",
        origin_key="url:https://exemplo.com.br",
    )
    assert any(e.display_name == "blog.exemplo.com.br" for e in wb.entities)
    scan = parse_urlscan_results(
        [{"page": {"domain": "shop.exemplo.com.br", "url": "https://shop.exemplo.com.br", "title": "contato contato@exemplo.com.br"}}],
        domain="exemplo.com.br",
        origin_key="url:https://exemplo.com.br",
    )
    assert any(e.kind == "EMAIL" and e.value == "contato@exemplo.com.br" for e in scan.entities)


def test_parse_email_keybase_and_gravatar() -> None:
    empty = parse_keybase_lookup({"status": {"code": 1}, "them": []}, email="a@b.com", origin_key="email:a@b.com")
    assert empty.entities == []
    kb = parse_keybase_lookup(
        {"status": {"code": 0}, "them": [{"basics": {"username": "alice"}}]},
        email="a@b.com",
        origin_key="email:a@b.com",
    )
    assert kb.entities[0].kind == "USERNAME"
    assert kb.entities[0].value == "alice"
    grav = parse_gravatar_entry(
        {"entry": [{"displayName": "Ana", "profileUrl": "https://gravatar.com/ana"}]},
        email="a@b.com",
        origin_key="email:a@b.com",
    )
    assert grav.entities[0].value == "https://gravatar.com/ana"


def test_describe_phone_ddd() -> None:
    info = describe_phone("11987654321")
    assert info["ddd"] == "11"
    assert info["cidade"] == "São Paulo"
    assert info["tipo"] == "celular"
    intl = describe_phone("5511987654321")
    assert intl["pais"] == "Brasil"
    assert intl["ddd"] == "11"


def test_parse_aleph_and_censys() -> None:
    aleph = parse_aleph_results(
        [{"id": "abc", "caption": "Maria Silva", "schema": "Person"}, {"id": "", "caption": "x"}],
        origin_key="name:maria silva",
    )
    assert aleph.entities[0].display_name == "Maria Silva"
    assert "aleph.occrp.org" in aleph.entities[0].value
    censys = parse_censys_hits(
        [{"ip": "203.0.113.9", "name": ["www.exemplo.com.br"], "location": {"city": "Santos", "country": "Brazil"}}],
        origin_key="url:https://exemplo.com.br",
    )
    assert censys.entities[0].display_name == "exemplo.com.br"
    assert "Santos" in (censys.evidence[0].snippet or "")
