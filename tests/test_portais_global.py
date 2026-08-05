"""Garantias globais de portais — particularidades por família de sistema."""

from __future__ import annotations

import pytest

from monitor_jus.official_portal import (
    _DEFAULT_PORTAIS,
    _portais_map,
    _is_useless_portal_url,
    resolve_official_link_result,
)

# CNJ alinhado ao segmento_tribunal (config/tribunais.yaml)
_COURT_CNJ: dict[str, str] = {
    "stf": "0000001-00.2024.1.00.0000",
    "stj": "0000001-00.2020.3.00.0000",
    "tst": "0000001-00.2020.5.00.0000",
    "tse": "0000001-00.2020.6.00.0000",
    "tjsp": "1000123-45.2023.8.26.0100",
    "tjrj": "0000123-45.2023.8.19.0001",
    "tjmg": "0000123-45.2023.8.13.0024",
    "tjrs": "0000123-45.2023.8.21.0001",
    "tjpr": "0000123-45.2023.8.18.0001",
    "tjsc": "0000123-45.2023.8.24.0001",
    "tjba": "0000123-45.2023.8.05.0001",
    "tjce": "0000123-45.2023.8.06.0001",
    "tjgo": "0000123-45.2023.8.09.0001",
    "tjdft": "0000123-45.2023.8.07.0001",
    "tjes": "0000123-45.2023.8.08.0001",
    "tjpe": "0000123-45.2023.8.16.0001",
    "tjpb": "0000123-45.2023.8.15.0001",
    "tjrn": "0000123-45.2023.8.20.0001",
    "tjma": "0000123-45.2023.8.10.0001",
    "tjmt": "0000123-45.2023.8.11.0001",
    "tjms": "0000123-45.2023.8.12.0001",
    "tjpa": "0000123-45.2023.8.14.0001",
    "tjpi": "0000123-45.2023.8.17.0001",
    "tjal": "0000123-45.2023.8.02.0001",
    "tjam": "0000123-45.2023.8.04.0001",
    "tjac": "0000123-45.2023.8.01.0001",
    "tjap": "0000123-45.2023.8.03.0001",
    "tjro": "0000123-45.2023.8.22.0001",
    "tjrr": "0000123-45.2023.8.23.0001",
    "tjse": "0000123-45.2023.8.25.0001",
    "tjto": "0000123-45.2023.8.27.0001",
    "trf1": "1000123-45.2023.4.01.3400",
    "trf2": "0000123-45.2023.4.02.5101",
    "trf3": "0000123-45.2023.4.03.6100",
    "trf4": "5000123-45.2023.4.04.7100",
    "trf5": "0000123-45.2023.4.05.8100",
    "trf6": "0000123-45.2023.4.06.3800",
}


@pytest.fixture(autouse=True)
def _clear_portal_cache():
    _portais_map.cache_clear()
    yield
    _portais_map.cache_clear()


@pytest.mark.parametrize("court,cnj", sorted(_COURT_CNJ.items()))
def test_every_court_builds_http_url(court: str, cnj: str):
    result = resolve_official_link_result(cnj, tribunal=court.upper())
    assert result.url.startswith("http"), court
    assert result.link_type != "UNAVAILABLE", court
    # URL deve carregar o número (dígitos ou CNJ) — evita homepage genérica
    digits = "".join(c for c in cnj if c.isdigit())
    assert digits[:7] in result.url or cnj.split("-")[0] in result.url or digits in result.url, (
        court,
        result.url,
    )


def test_esaj_family_uses_search_do():
    for court in ("tjsp", "tjms", "tjce", "tjal", "tjam"):
        r = resolve_official_link_result(_COURT_CNJ[court], tribunal=court.upper())
        assert "search.do" in r.url
        assert r.requires_manual_search is False
        assert r.confidence == "high"


def test_eproc_family_uses_process_number_param():
    for court in ("tjsc", "tjac", "tjse", "tjto", "trf2", "trf4", "trf6"):
        r = resolve_official_link_result(_COURT_CNJ[court], tribunal=court.upper())
        low = r.url.lower()
        assert "txtnumprocesso=" in low or "num_processo=" in low, (court, r.url)
        assert r.link_type == "PROCESS_SEARCH_PREFILLED"
        if court == "trf4":
            assert "eproc2trf4" in low
        if court == "tjac":
            assert "eproc1g.tjac" in low
        if court == "tjto":
            assert "processo_seleciona_publica" in low


def test_tjrj_requires_tipo_and_digits():
    r = resolve_official_link_result(_COURT_CNJ["tjrj"], tribunal="TJRJ")
    assert "tipoProcesso=13" in r.url
    assert "codigoProcesso=00001234520238190001" in r.url


def test_tst_has_structured_query():
    r = resolve_official_link_result(_COURT_CNJ["tst"], tribunal="TST")
    assert "numeroTst=" in r.url
    assert "digitoVerificador=" in r.url


def test_pje_marked_manual_even_with_query():
    r = resolve_official_link_result(_COURT_CNJ["tjma"], tribunal="TJMA")
    assert "listView.seam" in r.url
    assert r.requires_manual_search is True
    assert "numeroProcesso=" in r.url


def test_bare_eproc_without_number_is_useless():
    assert _is_useless_portal_url(
        "https://eproc.trf4.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica"
    )


def test_default_map_covers_main_courts():
    keys = set(_DEFAULT_PORTAIS)
    for court in _COURT_CNJ:
        assert court in keys, court
