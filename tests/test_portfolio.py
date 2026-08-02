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
