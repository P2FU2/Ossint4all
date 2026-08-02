from monitor_jus.official_portal import resolve_official_link


def test_stj_deep_link():
    link = resolve_official_link("0000001-00.2020.3.00.0000", tribunal="STJ")
    assert link is not None
    assert "processo.stj.jus.br" in link
    assert "00000010020203000000" in link or "termo=" in link


def test_tjsp_esaj_link():
    link = resolve_official_link("1000123-45.2023.8.26.0100", tribunal="TJSP")
    assert link is not None
    assert "esaj.tjsp.jus.br" in link
    assert "1000123-45.2023.8.26.0100" in link


def test_prefers_payload_url():
    link = resolve_official_link(
        "1000123-45.2023.8.26.0100",
        tribunal="TJSP",
        payload={"url": "https://exemplo.jus.br/processo/abc"},
    )
    assert link == "https://exemplo.jus.br/processo/abc"


def test_existing_link_wins():
    link = resolve_official_link(
        "1000123-45.2023.8.26.0100",
        existing="https://portal.oficial/xyz",
        payload={"url": "https://outro"},
    )
    assert link == "https://portal.oficial/xyz"
