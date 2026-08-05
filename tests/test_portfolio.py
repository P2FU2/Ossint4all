from collections import Counter
from types import SimpleNamespace

from monitor_jus.pipeline.portfolio import (
    _include_all_oab_criteria,
    classify_outcome,
    criterion_display_label,
    oab_labels_for_process,
)


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


def test_criterion_display_label_oab_with_letter_suffix():
    crit = SimpleNamespace(criterion_type="OAB", value="RJ:2556A", label=None)
    assert criterion_display_label(crit) == "OAB 2556A/RJ"


def test_include_all_oab_criteria_shows_zero_counts():
    criteria = {
        "1": SimpleNamespace(criterion_type="OAB", value="RJ:2556A", label=None),
        "2": SimpleNamespace(criterion_type="OAB", value="SP:138094", label=None),
        "3": SimpleNamespace(criterion_type="NOME", value="Fulano", label="Fulano"),
    }
    by_oab = Counter({"OAB 138094/SP": 10})
    _include_all_oab_criteria(criteria, by_oab)
    assert by_oab["OAB 138094/SP"] == 10
    assert by_oab["OAB 2556A/RJ"] == 0
    assert "Nome · Fulano" not in by_oab


def test_oab_labels_from_payload_even_without_link():
    """Processo achado só por nome, mas com OAB no DJEN, conta na Por OAB."""
    crit_sp = SimpleNamespace(criterion_type="OAB", value="SP:138094", label=None)
    crit_rj = SimpleNamespace(criterion_type="OAB", value="RJ:2556", label=None)
    payload = {
        "djen": {
            "destinatarioadvogados": [
                {"advogado": {"numero_oab": "138094", "uf_oab": "SP"}}
            ]
        }
    }
    labels = oab_labels_for_process(
        link_labels=["Nome · Fernando Crespo Queiroz Neves"],
        payload=payload,
        oab_criteria=[crit_sp, crit_rj],
    )
    assert labels == {"OAB 138094/SP"}
