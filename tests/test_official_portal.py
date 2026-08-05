import pytest

from monitor_jus.official_portal import (
    _is_useless_portal_url,
    resolve_official_link,
    resolve_official_link_result,
)

CNJ_STF = "0000001-00.2024.1.00.0000"
CNJ_STJ = "0000001-00.2020.3.00.0000"
CNJ_TRF1 = "1000123-45.2023.4.01.3400"
CNJ_TJSP_1G = "1000123-45.2023.8.26.0100"
CNJ_TJSP_2G = "2136744-60.2026.8.26.0000"


@pytest.mark.parametrize(
    ("court", "cnj", "expected_type"),
    [
        ("STF", CNJ_STF, "PROCESS_SEARCH_PREFILLED"),
        ("STJ", CNJ_STJ, "PROCESS_SEARCH_PREFILLED"),
        ("TRF1", CNJ_TRF1, "PROCESS_SEARCH_PREFILLED"),
        ("TJSP", CNJ_TJSP_1G, "PROCESS_SEARCH_PREFILLED"),
    ],
)
def test_official_links(court, cnj, expected_type):
    result = resolve_official_link_result(cnj, tribunal=court)
    assert result.link_type == expected_type
    assert result.url.startswith("http")
    assert result.link_type != "COURT_HOMEPAGE"


def test_tjsp_agravo_uses_cposg():
    result = resolve_official_link_result(
        CNJ_TJSP_2G,
        tribunal="TJSP",
        classe="Agravo de Instrumento",
    )
    assert "cposg" in result.url
    assert "2136744-60.2026" in result.url
    assert "cpopg" not in result.url


def test_tjsp_origem_0000_uses_cposg():
    result = resolve_official_link_result(CNJ_TJSP_2G, tribunal="TJSP")
    assert "cposg" in result.url


def test_tjsp_1g_uses_cpopg():
    result = resolve_official_link_result(CNJ_TJSP_1G, tribunal="TJSP")
    assert "cpopg" in result.url
    assert "1000123-45.2023.8.26.0100" in result.url


def test_rejects_dje_homepage():
    assert _is_useless_portal_url("https://www.dje.tjsp.jus.br")
    assert _is_useless_portal_url("https://www.dje.tjsp.jus.br/")


def test_rejects_judit_homepage():
    assert _is_useless_portal_url("https://www.judit.io/")


def test_rejects_empty_pje_listview():
    assert _is_useless_portal_url(
        "https://pje1g.trf1.jus.br/consultapublica/ConsultaPublica/listView.seam"
    )


def test_prefers_esaj_show_deep_link():
    deep = (
        "https://esaj.tjsp.jus.br/cpopg/show.do?"
        "processo.codigo=2S0022OZI0000&processo.foro=100"
        "&processo.numero=0063467-70.2025.8.26.0100"
    )
    result = resolve_official_link_result(
        "0063467-70.2025.8.26.0100",
        tribunal="TJSP",
        existing=deep,
    )
    assert result.link_type == "PROCESS_DEEP_LINK"
    assert result.url == deep


def test_ignores_useless_djen_link_and_builds_search():
    result = resolve_official_link_result(
        CNJ_TJSP_1G,
        tribunal="TJSP",
        payload={"link": "https://www.dje.tjsp.jus.br", "djen": {"link": "https://www.dje.tjsp.jus.br"}},
    )
    assert "esaj.tjsp.jus.br" in result.url
    assert "cpopg" in result.url


def test_recomputes_link_in_email():
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
    link = resolve_official_link(CNJ_TJSP_1G, tribunal="TJSP")
    assert link is not None
    assert "esaj.tjsp.jus.br" in link
    assert "1000123-45.2023.8.26.0100" in link


CNJ_TJRJ = "3062640-09.2025.8.19.0001"


def test_tjrj_uses_digits_and_tipo_processo_13():
    result = resolve_official_link_result(CNJ_TJRJ, tribunal="TJRJ")
    assert result.link_type == "PROCESS_SEARCH_PREFILLED"
    assert "consultapublicap" in result.url
    assert "codigoProcesso=30626400920258190001" in result.url
    assert "tipoProcesso=13" in result.url
    assert "numProcesso=" not in result.url
    # CNJ com ponto sozinho não deve ser usado (página em branco)
    assert "3062640-09.2025" not in result.url


def test_tjrj_rejects_blank_cnj_only_detail_and_rebuilds():
    result = resolve_official_link_result(
        CNJ_TJRJ,
        tribunal="TJRJ",
        existing=(
            "https://www3.tjrj.jus.br/consultaprocessual/"
            f"#/consultapublicap?codigoProcesso={CNJ_TJRJ}"
        ),
    )
    assert "tipoProcesso=13" in result.url
    assert "codigoProcesso=30626400920258190001" in result.url


CNJ_TJMS = "0800123-45.2023.8.12.0001"


def test_tjms_uses_esaj_search_not_open():
    result = resolve_official_link_result(CNJ_TJMS, tribunal="TJMS")
    assert "esaj.tjms.jus.br" in result.url
    assert "search.do" in result.url
    assert "open.do" not in result.url
    assert "0800123-45.2023" in result.url


def test_tjms_rejects_open_do_homepage():
    result = resolve_official_link_result(
        CNJ_TJMS,
        tribunal="TJMS",
        existing="https://esaj.tjms.jus.br/cpopg/open.do",
    )
    assert "search.do" in result.url


def test_trf3_avoids_empty_pje_listview():
    cnj = "0000123-45.2023.4.03.6100"
    result = resolve_official_link_result(cnj, tribunal="TRF3")
    assert "listview.seam" not in result.url.lower()
    assert "trf3.jus.br" in result.url.lower()


def test_prefers_payload_url_when_useful():
    link = resolve_official_link(
        CNJ_TJSP_1G,
        tribunal="TJSP",
        payload={"url": "https://exemplo.jus.br/processo/abc"},
    )
    assert link == "https://exemplo.jus.br/processo/abc"


def test_stf_lawyer_search():
    result = resolve_official_link_result(
        None,
        tribunal="STF",
        lawyer_name="Fernando Crespo Queiroz Neves",
    )
    assert result.link_type == "COURT_SEARCH_PAGE"
    assert result.requires_manual_search is True
    assert "parte=" in result.url
