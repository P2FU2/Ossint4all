from monitor_jus.sources.datajud_router import resolve_process_source


def test_stf_never_datajud():
    route = resolve_process_source("0000001-00.2024.1.00.0000", "STF")
    assert route.source == "STF_DJEN_PORTAL"
    assert route.datajud_alias is None


def test_stj_alias():
    route = resolve_process_source("0000001-00.2020.3.00.0000", "STJ")
    assert route.source == "DATAJUD"
    assert route.datajud_alias == "api_publica_stj"


def test_trf1_alias():
    route = resolve_process_source("1000123-45.2023.4.01.3400", "TRF1")
    assert route.source == "DATAJUD"
    assert route.datajud_alias == "api_publica_trf1"
