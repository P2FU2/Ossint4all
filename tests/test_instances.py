from monitor_jus.instances import (
    InstanceLevel,
    instance_from_cnj_court,
    instance_label,
    summarize_instances,
)
from monitor_jus.pipeline.normalize import normalize_datajud_hits
from monitor_jus.sources.datajud import prefer_datajud_hit


def test_fundamental_degrees():
    assert instance_from_cnj_court(None, "TJSP", grau="G1") == InstanceLevel.PRIMEIRO_GRAU
    assert instance_from_cnj_court(None, "TJSP", grau="G2") == InstanceLevel.SEGUNDO_GRAU
    assert instance_label(InstanceLevel.PRIMEIRO_GRAU) == "1º grau"
    assert instance_label(InstanceLevel.SEGUNDO_GRAU) == "2º grau"


def test_superior_and_stf_by_court_and_cnj():
    assert instance_from_cnj_court(None, "STJ") == InstanceLevel.SUPERIOR
    assert instance_from_cnj_court(None, "STF") == InstanceLevel.STF
    # segmento 3 = STJ
    assert (
        instance_from_cnj_court("0000001-00.2020.3.00.0000", None)
        == InstanceLevel.SUPERIOR
    )
    # segmento 1 = STF
    assert (
        instance_from_cnj_court("0000001-00.2020.1.00.0000", None) == InstanceLevel.STF
    )


def test_summarize_fundamental_pair():
    summary = summarize_instances(
        [
            {"grau": "G1", "tribunal": "TJSP"},
            {"grau": "G2", "tribunal": "TJSP"},
        ]
    )
    assert summary["has_fundamental_pair"] is True
    assert summary["active_label"] == "2º grau"
    assert summary["reached_superior"] is False


def test_prefer_and_normalize_expose_instance_labels():
    g1 = {"grau": "G1", "tribunal": "TJSP", "movimentos": []}
    g2 = {
        "grau": "G2",
        "tribunal": "TJSP",
        "movimentos": [{"nome": "Acórdão", "dataHora": "2026-01-01T00:00:00.000Z"}],
        "dataHoraUltimaAtualizacao": "2026-01-02T00:00:00.000Z",
    }
    assert prefer_datajud_hit([g1, g2])["grau"] == "G2"
    norm = normalize_datajud_hits([g1, g2])
    assert norm["instance_label"] == "2º grau"
    assert norm["instance_summary"]["has_fundamental_pair"] is True
    assert {i["instance_label"] for i in norm["instances"]} == {"1º grau", "2º grau"}
