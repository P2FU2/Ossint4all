from monitor_jus.pipeline.status_oficial import (
    extract_status_from_payload,
    normalize_situacao_key,
    resolve_situacao_oficial,
)


def test_placeholder_falls_back_to_steps_arquivado_as_extinto():
    payload = {
        "status": "---",
        "last_step": {"content": "Juntada de petição"},
        "steps": [
            {"content": "Distribuído"},
            {"content": "Arquivado Definitivamente"},
        ],
    }
    text = extract_status_from_payload(payload)
    assert text == "Extinto"
    label, key = resolve_situacao_oficial("---", payload=payload)
    assert key == "extinto"
    assert label == "Extinto"


def test_em_grau_de_recurso():
    assert normalize_situacao_key("Em grau de recurso") == "em_grau_de_recurso"
    label, key = resolve_situacao_oficial("Em grau de recurso")
    assert key == "em_grau_de_recurso"
    assert label == "Em grau de recurso"


def test_explicit_extinto():
    label, key = resolve_situacao_oficial("Extinto")
    assert key == "extinto"
    assert label == "Extinto"


def test_ignores_template_placeholders():
    assert extract_status_from_payload({"status": "Publicado #{ato_publicado} em #{data}."}) is None


def test_cancelado_from_movement():
    assert normalize_situacao_key("Incidente Processual Cancelado") == "cancelado"
    assert normalize_situacao_key("Determinado o cancelamento da distribuição") == "cancelado"
    label, key = resolve_situacao_oficial(
        None,
        last_movement="Incidente Processual Cancelado",
    )
    assert key == "cancelado"
    assert label == "Cancelado"


def test_suspenso_and_encerrado_grau():
    assert normalize_situacao_key("Suspenso") == "suspenso"
    assert normalize_situacao_key("2º Grau Encerrado") == "encerrado"
    label, key = resolve_situacao_oficial("2º Grau Encerrado")
    assert key == "encerrado"
    assert label == "Encerrado"


def test_datajud_payload_prefers_terminal_over_intimacao():
    payload = {
        "datajud": {
            "situacao": None,
            "last_movement_name": "Expedida/certificada a intimação eletrônica",
            "instances": [
                {"last_movement_name": "Incidente Processual Cancelado"},
            ],
        }
    }
    text = extract_status_from_payload(payload)
    assert text == "Cancelado"
    _, key = resolve_situacao_oficial(None, payload=payload)
    assert key == "cancelado"
