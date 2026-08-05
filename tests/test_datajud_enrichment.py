from monitor_jus.pipeline.normalize import normalize_datajud_hits
from monitor_jus.pipeline.status_oficial import normalize_situacao_key
from monitor_jus.sources.datajud import prefer_datajud_hit


G1 = {
    "grau": "G1",
    "tribunal": "TJSP",
    "classe": {"nome": "Demarcação / Divisão"},
    "orgaoJulgador": {"nome": "01 CUMULATIVA DE CASA BRANCA"},
    "assuntos": [{"nome": "Divisão e Demarcação", "principal": True}],
    "movimentos": [
        {"nome": "Remessa", "dataHora": "2025-01-31T12:14:59.000Z"},
        {"nome": "Publicação", "dataHora": "2025-01-31T22:08:01.000Z"},
    ],
    "dataHoraUltimaAtualizacao": "2025-01-31T22:08:01.000Z",
}

G2 = {
    "grau": "G2",
    "tribunal": "TJSP",
    "classe": {"nome": "Embargos de Declaração Cível"},
    "orgaoJulgador": {"nome": "2ª CÂMARA DE DIREITO PRIVADO"},
    "assuntos": [{"nome": "Divisão e Demarcação", "principal": True}],
    "movimentos": [
        {"nome": "Outras Decisões", "dataHora": "2026-04-16T16:59:08.000Z"},
        {"nome": "Conclusão", "dataHora": "2026-04-22T13:31:10.000Z"},
    ],
    "dataHoraUltimaAtualizacao": "2026-04-22T13:31:10.000Z",
}


def test_prefer_g2_over_g1():
    hit = prefer_datajud_hit([G1, G2])
    assert hit["grau"] == "G2"


def test_normalize_hits_sets_julgado_and_g2_capa():
    norm = normalize_datajud_hits([G1, G2])
    assert norm["grau"] == "G2"
    assert norm["classe"] == "Embargos de Declaração Cível"
    assert norm["orgao_julgador"] == "2ª CÂMARA DE DIREITO PRIVADO"
    assert norm["assunto"] == "Divisão e Demarcação"
    assert norm["has_second_degree"] is True
    assert norm["situacao"] == "Julgado"
    assert len(norm["instances"]) == 2
    assert norm["instance_label"] == "2º grau"
    assert norm["instance_summary"]["has_fundamental_pair"] is True


def test_situacao_key_julgado():
    assert normalize_situacao_key("Julgado") == "julgado"
