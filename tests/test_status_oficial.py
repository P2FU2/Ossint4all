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
