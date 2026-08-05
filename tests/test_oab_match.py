from monitor_jus.oab_match import (
    criterion_matches_oab,
    extract_oabs_from_payload,
    filter_matches_oab_text,
    oab_search_keys,
    parse_oab_filter,
)


def test_oab_search_keys_with_letter_fallback():
    assert oab_search_keys("2556A", "RJ") == ["2556ARJ", "2556RJ"]
    assert oab_search_keys("138094", "SP") == ["138094SP"]


def test_parse_oab_filter_formats():
    assert parse_oab_filter("2556/RJ") == ("2556", "RJ")
    assert parse_oab_filter("OAB 2556A/RJ") == ("2556", "RJ")
    assert parse_oab_filter("RJ:2556") == ("2556", "RJ")
    assert parse_oab_filter("Fernando") is None


def test_extract_oabs_from_payload_parties():
    payload = {
        "parties": [
            {
                "name": "CLARO S.A.",
                "lawyers": [
                    {
                        "name": "FERNANDO CRESPO QUEIROZ NEVES",
                        "documents": [
                            {
                                "document_type": "oab",
                                "document": "2556",
                                "document_extra": "RJ",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    assert ("2556", "RJ") in extract_oabs_from_payload(payload)


def test_extract_oabs_from_slash_text():
    payload = {"raw": "Advogado FERNANDO CRESPO QUEIROZ NEVES OAB 2556/RJ"}
    assert ("2556", "RJ") in extract_oabs_from_payload(payload)


def test_extract_oabs_from_djen_structured_fields():
    """DJEN usa numero_oab + uf_oab separados — não aparece como 138094/SP no JSON."""
    payload = {
        "djen": {
            "destinatarioadvogados": [
                {
                    "advogado": {
                        "nome": "FERNANDO CRESPO QUEIROZ NEVES",
                        "numero_oab": "138094",
                        "uf_oab": "SP",
                    }
                }
            ]
        }
    }
    assert ("138094", "SP") in extract_oabs_from_payload(payload)


def test_criterion_matches_ignores_letter_suffix():
    assert criterion_matches_oab("RJ:2556A", ("2556", "RJ")) is True
    assert criterion_matches_oab("RJ:2556", ("2556", "RJ")) is True
    assert criterion_matches_oab("SP:138094", ("2556", "RJ")) is False


def test_filter_matches_oab_text():
    labels = "OAB 138094/SP, Nome · Fernando"
    assert filter_matches_oab_text("138094/SP", labels) is True
    assert filter_matches_oab_text("OAB 138094/SP", labels) is True
    assert filter_matches_oab_text("fernando", labels) is True
    assert filter_matches_oab_text("2556/RJ", labels) is False
