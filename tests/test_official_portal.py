import pytest

from monitor_jus.official_portal import (
    _is_useless_portal_url,
    resolve_official_link,
    resolve_official_link_result,
)

CNJ_STF = "0000001-00.2024.1.00.0000"
CNJ_STJ = "0000001-00.2020.3.00.0000"
CNJ_TRF1 = "1000123-45.2023.4.01.3400"
CNJ_TJSP = "1000123-45.2023.8.26.0100"


@pytest.mark.parametrize(
    ("court", "cnj", "expected_type"),
    [
        ("STF", CNJ_STF, "PROCESS_SEARCH_PREFILLED"),
        ("STJ", CNJ_STJ, "PROCESS_SEARCH_PREFILLED"),
        ("TRF1", CNJ_TRF1, "PROCESS_SEARCH_PREFILLED"),
        ("TJSP", CNJ_TJSP, "PROCESS_DEEP_LINK"),
    ],
)
def test_official_links(court, cnj, expected_type):
    result = resolve_official_link_result(cnj, tribunal=court)
    assert result.link_type == expected_type
    assert result.url.startswith("http")
    assert result.link_type != "COURT_HOMEPAGE"


def test_rejects_judit_homepage():
    assert _is_useless_portal_url("https://www.judit.io/")


def test_rejects_empty_pje_listview():
    assert _is_useless_portal_url(
        "https://pje1g.trf1.jus.br/consultapublica/ConsultaPublica/listView.seam"
    )


def test_recomputes_link_in_email():
    # existing useless URL is ignored in favor of recomputed portal
    result = resolve_official_link_result(
        CNJ_STJ,
        tribunal="STJ",
        existing="https://www.judit.io/lawsuit/abc",
    )
    assert "stj.jus.br" in result.url
    assert result.link_type == "PROCESS_SEARCH_PREFILLED"


def test_stj_deep_link():
    link = resolve_official_link(CNJ_STJ, tribunal="STJ")
    assert link is not None
    assert "processo.stj.jus.br" in link


def test_tjsp_esaj_link():
    link = resolve_official_link(CNJ_TJSP, tribunal="TJSP")
    assert link is not None
    assert "esaj.tjsp.jus.br" in link
    assert "1000123-45.2023.8.26.0100" in link


def test_prefers_payload_url_when_useful():
    link = resolve_official_link(
        CNJ_TJSP,
        tribunal="TJSP",
        payload={"url": "https://exemplo.jus.br/processo/abc"},
    )
    assert link == "https://exemplo.jus.br/processo/abc"


def test_existing_link_wins_when_useful():
    link = resolve_official_link(
        CNJ_TJSP,
        existing="https://portal.oficial/xyz",
        payload={"url": "https://outro"},
    )
    assert link == "https://portal.oficial/xyz"


def test_stf_lawyer_search():
    result = resolve_official_link_result(
        None,
        tribunal="STF",
        lawyer_name="Fernando Crespo Queiroz Neves",
    )
    assert result.link_type == "COURT_SEARCH_PAGE"
    assert result.requires_manual_search is True
    assert "parte=" in result.url
