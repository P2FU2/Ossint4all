from monitor_jus.oab_match import oab_search_keys
from monitor_jus.sources.judit.requests import oab_search_key


def test_oab_search_key_format():
    assert oab_search_key("138094", "SP") == "138094SP"
    assert oab_search_key("2556A", "rj") == "2556ARJ"
    assert oab_search_key("74043", "DF") == "74043DF"


def test_oab_search_keys_fallback_digits():
    assert oab_search_keys("2556A", "RJ") == ["2556ARJ", "2556RJ"]
