from monitor_jus.sources.judit.requests import oab_search_key


def test_oab_search_key_format():
    assert oab_search_key("138094", "SP") == "138094SP"
    assert oab_search_key("2556A", "rj") == "2556ARJ"
    assert oab_search_key("74043", "DF") == "74043DF"
