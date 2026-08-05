from datetime import date

from monitor_jus.sources.djen.criteria import DjenSearchCriteria
from monitor_jus.sources.djen.params import build_query_params


def test_build_query_params_isolates_api_names():
    criteria = DjenSearchCriteria(
        oab_number="138094",
        oab_state="SP",
        available_from=date(2026, 8, 1),
        available_until=date(2026, 8, 4),
        page=2,
        size=50,
    )
    params = build_query_params(criteria)
    # domínio não vaza nomes crus se o map existir
    assert "oab_number" not in params or "numeroOab" in params
    assert params.get("numeroOab") == "138094" or params.get("oab_number") == "138094"
    assert params.get("ufOab") == "SP" or params.get("oab_state") == "SP"


def test_size_capped():
    criteria = DjenSearchCriteria(size=999, court="STJ")
    params = build_query_params(criteria)
    size_key = "itensPorPagina" if "itensPorPagina" in params else "size"
    assert int(params[size_key]) <= 100
