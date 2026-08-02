from pathlib import Path

from monitor_jus.models import Priority
from monitor_jus.pipeline.prioritize import classify_priority, has_possible_deadline


def test_sentenca_com_intimacao_alta():
    p, rule = classify_priority(
        "Sentença proferida. Intimação das partes.",
        Path("config/prioridades.yaml"),
    )
    assert p == Priority.ALTA
    assert rule == "sentenca_com_intimacao"


def test_sentenca_isolada_media():
    p, rule = classify_priority("Sentença de mérito.", Path("config/prioridades.yaml"))
    assert p == Priority.MEDIA
    assert rule == "sentenca_isolada"


def test_deadline_flag():
    assert has_possible_deadline("Prazo de 15 dias úteis") is True
