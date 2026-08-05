from monitor_jus.sources.djen.extract import extract_communication


SAMPLE = {
    "id": 685668795,
    "data_disponibilizacao": "2026-08-04",
    "siglaTribunal": "TJMG",
    "tipoComunicacao": "Intimação",
    "texto": "Adv - FERNANDO C QUEIROZ NEVES",
    "numero_processo": "52453993020078130024",
    "hash": "PpDAj7XqYvAIbPWC4Tny43kZrvMJbg",
    "numeroprocessocommascara": "5245399-30.2007.8.13.0024",
    "destinatarios": [{"nome": "BANCO BRADESCO S/A", "polo": "A"}],
    "destinatarioadvogados": [
        {
            "advogado": {
                "nome": "FERNANDO C QUEIROZ NEVES",
                "numero_oab": "138094",
                "uf_oab": "SP",
            }
        },
        {
            "advogado": {
                "nome": "OUTRO ADVOGADO",
                "numero_oab": "103181",
                "uf_oab": "MG",
            }
        },
    ],
    "link": "https://www4.tjmg.jus.br/exemplo",
}


def test_extract_prefers_masked_cnj_and_structured_oab():
    out = extract_communication(SAMPLE)
    assert out["external_id"] == "685668795"
    assert out["process_number"] == "5245399-30.2007.8.13.0024"
    assert out["court"] == "TJMG"
    assert out["availability_date"] == "2026-08-04"
    canons = {o.canonical for o in out["oabs"]}
    assert "SP-138094" in canons
    assert "MG-103181" in canons
    assert "FERNANDO C QUEIROZ NEVES" in out["lawyer_names"]
    assert out["source_link"].startswith("https://")
