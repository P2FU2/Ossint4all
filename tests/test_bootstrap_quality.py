"""Bootstrap: não fechar baseline se DJEN não entregou."""

from __future__ import annotations

from monitor_jus.pipeline.bootstrap import _discovery_quality


def test_discovery_quality_all_failed():
    ok, note = _discovery_quality(
        {
            "total_active_criteria": 4,
            "successful_criteria": 0,
            "errors": [{"criterion": "x", "error": "403"}],
        }
    )
    assert ok is False
    assert "Diário da Justiça" in note
    assert "minutos" in note.lower()


def test_discovery_quality_skipped_djen():
    ok, note = _discovery_quality({"status": "skipped", "reason": "djen_disabled"})
    assert ok is False
    assert "desabilitado" in note.lower()


def test_discovery_quality_full_ok():
    ok, note = _discovery_quality(
        {"total_active_criteria": 4, "successful_criteria": 4, "errors": []}
    )
    assert ok is True
    assert note == ""


def test_discovery_quality_partial_is_not_ok():
    ok, note = _discovery_quality(
        {
            "total_active_criteria": 4,
            "successful_criteria": 2,
            "errors": [{"criterion": "x", "error": "403"}],
        }
    )
    assert ok is False
    assert "2 de 4" in note


def test_discovery_quality_zero_criteria():
    ok, note = _discovery_quality(
        {"total_active_criteria": 0, "successful_criteria": 0, "errors": []}
    )
    assert ok is False
    assert "critério" in note.lower()


def test_discovery_quality_saturated_not_ok():
    ok, note = _discovery_quality(
        {
            "total_active_criteria": 2,
            "successful_criteria": 2,
            "errors": [],
            "saturated_criteria": ["OAB:SP:1"],
        }
    )
    assert ok is False
    assert "truncada" in note.lower() or "páginas" in note.lower()


def test_source_job_type_labels():
    from monitor_jus.pipeline.discovery import _source_job_type

    assert _source_job_type(purpose="bootstrap", mode="historical") == "BOOTSTRAP"
    assert _source_job_type(purpose="discovery", mode="historical") == "HISTORICAL_DISCOVERY"
    assert _source_job_type(purpose="discovery", mode="incremental") == "DJEN_POLL"


def test_progress_complete_keeps_totals(monkeypatch):
    from monitor_jus import progress as progress_mod

    monkeypatch.setattr(progress_mod, "_persist", lambda *a, **k: None)
    progress_mod.clear_job()
    progress_mod.bind_job("job-b", "run-b")
    progress_mod.report(stage="bootstrap", done=2, total=3, message="meio", force=True)
    progress_mod.complete("Bootstrap incompleto — aviso")
    assert progress_mod._state is not None
    assert progress_mod._state.total == 3
    assert progress_mod._state.done == 3
    assert "incompleto" in progress_mod._state.message.lower()
    progress_mod.clear_job()
