from osint4all.intel.google import classify_google_url, public_google_hints
from osint4all.intel.hosts import (
    correlate_hosts,
    extract_same_domain_links,
    is_public_hostname,
    observation_from_payload,
    parse_banner_record,
    parse_http_snapshot,
    parse_imported_host_rows,
    parse_robots,
    parse_security_txt,
    upsert_host_intel,
)
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed


def test_hostname_rejects_scan_targets() -> None:
    assert is_public_hostname("exemplo.com.br")
    assert not is_public_hostname("127.0.0.1")
    assert not is_public_hostname("10.0.0.8")
    assert not is_public_hostname("localhost")
    assert not is_public_hostname("169.254.169.254")


def test_http_snapshot_and_photon_links() -> None:
    html = (
        "<html><head><title>Portal Público</title>"
        '<meta name="generator" content="WordPress 6.4"></head>'
        '<body><a href="/sobre">Sobre</a><a href="https://outro.com/x">fora</a>'
        '<a href="mailto:a@b.com">mail</a></body></html>'
    )
    obs = parse_http_snapshot(
        "https://www.exemplo.com.br/",
        status=200,
        headers={"Server": "nginx", "X-Powered-By": "PHP/8.3"},
        html=html,
    )
    assert obs is not None
    assert obs.host == "exemplo.com.br"
    assert obs.status == 200
    assert obs.title == "Portal Público"
    assert "nginx" in obs.tech
    assert "WordPress 6.4" in obs.tech
    links = extract_same_domain_links(html, "exemplo.com.br")
    assert any(item.endswith("/sobre") for item in links)
    assert all("outro.com" not in item for item in links)


def test_security_txt_and_robots_are_informative() -> None:
    fields = parse_security_txt("# comment\nContact: mailto:sec@exemplo.com.br\nPolicy: https://exemplo.com.br/security\n")
    assert ("contact", "sec@exemplo.com.br") in fields
    assert ("policy", "https://exemplo.com.br/security") in fields
    maps = parse_robots("User-agent: *\nDisallow: /admin\nSitemap: https://exemplo.com.br/sitemap.xml\n")
    assert maps == ["https://exemplo.com.br/sitemap.xml"]


def test_import_skips_ip_only_masscan_and_reads_zgrab() -> None:
    empty = parse_imported_host_rows([{"ip": "203.0.113.9", "ports": [{"port": 80}]}])
    assert empty == []
    zgrab = parse_imported_host_rows(
        {
            "domain": "exemplo.com.br",
            "ip": "203.0.113.9",
            "data": {"http": {"result": {"response": {"status_code": 200, "headers": {"server": ["nginx"]}}}}},
        }
    )
    assert zgrab[0].host == "exemplo.com.br"
    assert zgrab[0].status == 200
    assert "nginx" in zgrab[0].tech
    assert zgrab[0].origin == "import"


def test_banner_and_payload_normalize() -> None:
    obs = parse_banner_record({"host": "loja.exemplo.com.br", "product": "Apache", "title": "Loja", "source": "shodan"})
    assert obs is not None
    assert obs.host == "loja.exemplo.com.br"
    from_payload = observation_from_payload(
        {"host": "loja.exemplo.com.br", "produto": "Apache", "title": "Loja", "origin": "passive"},
        source="shodan_public",
    )
    cards = correlate_hosts([obs, from_payload])
    assert len(cards) == 1
    assert cards[0].host == "loja.exemplo.com.br"
    assert "shodan" in cards[0].sources[0] or "shodan_public" in cards[0].sources


def test_google_public_hints_have_no_session() -> None:
    assert classify_google_url("https://scholar.google.com/citations?user=x") == "Google Scholar"
    assert classify_google_url("https://exemplo.com") is None
    hints = public_google_hints(query="Ana Silva", username="ana")
    urls = " ".join(url for _, _, url in hints)
    assert "scholar.google.com" in urls
    assert "youtube.com/@ana" in urls
    assert "cookie" not in urls.lower()


def test_upsert_host_intel_merges_history(db) -> None:
    seed = parse_seed("https://exemplo.com.br", forced_kind="URL")
    inv = create_investigation(db, title="Host", hypothesis=None, seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t")
    entity = inv.entities[0]
    first = observation_from_payload({"host": "exemplo.com.br", "title": "A", "tech": ["nginx"], "origin": "passive"}, source="host_public")
    second = parse_http_snapshot("https://exemplo.com.br/", status=200, headers={"Server": "nginx"}, html="<title>Portal</title>")
    assert first and second
    upsert_host_intel(db, inv, entity.id, first)
    upsert_host_intel(db, inv, entity.id, second)
    db.flush()
    from osint4all.intel.hosts import cards_for_host

    cards = cards_for_host(db, inv.id, "exemplo.com.br")
    assert len(cards) == 1
    assert set(cards[0].sources) == {"host_public", "observe_http"}
    assert "nginx" in cards[0].tech
