from osint4all.connectors.datajud import alias_for_cnj, parse_datajud_hit
from osint4all.connectors.djen import parse_djen_items


def test_datajud_alias_tjsp() -> None:
    assert alias_for_cnj("0000001-23.2024.8.26.0100") == "api_publica_tjsp"
    assert alias_for_cnj("0000001-23.2024.1.00.0000") is None


def test_parse_datajud_parties() -> None:
    hit = {
        "tribunal": "TJSP",
        "classe": {"nome": "Procedimento Comum"},
        "assuntos": [{"nome": "Contratos"}],
        "poloAtivo": [{"nome": "EMPRESA ALFA LTDA", "advogados": [{"nome": "ADVOGADO UM"}]}],
        "poloPassivo": ["JOAO DA SILVA"],
        "movimentos": [{"nome": "Distribuído", "dataHora": "2024-01-01"}],
    }
    result = parse_datajud_hit(hit, "00000012320248260100")
    assert any(e.entity_type == "CASE" for e in result.entities)
    assert any(e.rel_type == "PARTE" for e in result.edges)
    assert any(e.rel_type == "ADVOGADO" for e in result.edges)
    assert result.evidence


def test_parse_djen_publication() -> None:
    items = [
        {
            "numeroprocessocommascara": "0000001-23.2024.8.26.0100",
            "siglaTribunal": "TJSP",
            "texto": "Intimação da parte",
            "tipoComunicacao": "Intimação",
            "link": "https://comunica.pje.jus.br/x",
            "destinatarioadvogados": [{"advogado": {"nome": "ADVOGADO UM"}}],
        }
    ]
    result = parse_djen_items(items, origin_key="name:maria silva souza")
    assert any(e.entity_type == "PUBLICATION" for e in result.entities)
    assert any(e.entity_type == "CASE" for e in result.entities)
    assert any(e.rel_type == "MENCAO" for e in result.edges)
