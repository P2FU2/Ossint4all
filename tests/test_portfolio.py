from monitor_jus.pipeline.portfolio import classify_outcome


def test_classify_outcome_exito():
    assert classify_outcome("Procedente") == "exito"
    assert classify_outcome("Homologação de acordo") == "exito"


def test_classify_outcome_derrota():
    assert classify_outcome("Improcedente") == "derrota"


def test_classify_outcome_encerrado():
    assert classify_outcome("Arquivado definitivamente") == "encerrado"


def test_classify_outcome_ativo():
    assert classify_outcome("Em andamento") == "ativo"
    assert classify_outcome("Conclusos para despacho") == "ativo"
    assert classify_outcome("Juntada de petição") == "ativo"
    assert classify_outcome("Ato ordinatório praticado") == "ativo"


def test_classify_outcome_indefinido_placeholder():
    assert classify_outcome("---") == "indefinido"
    assert classify_outcome("INCONSISTENTE") == "indefinido"
    assert classify_outcome(None) == "indefinido"


def test_classify_outcome_default_tramitacao():
    assert classify_outcome("Remetidos os Autos a Outro Juízo") == "ativo"
