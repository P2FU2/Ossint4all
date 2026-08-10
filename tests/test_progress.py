"""Testes do rastreador de progresso."""

from __future__ import annotations

from monitor_jus.progress import (
    bind_job,
    clear_job,
    format_bar,
    format_eta,
    format_progress_summary,
    report,
)


def test_format_bar_and_eta():
    assert format_bar(0) == "[" + ("-" * 20) + "]"
    assert format_bar(100) == "[" + ("#" * 20) + "]"
    assert format_eta(0) == "0s"
    assert format_eta(90).startswith("1m")
    assert format_eta(None) == "—"


def test_format_progress_summary_from_message():
    s = format_progress_summary(
        done=0.34,
        total=4.0,
        message="critério 1/4 · OAB 138094/SP · CNJ 114/330 · 1052670-48.2014.8.26.0053",
    )
    assert "Critério 1/4" in s
    assert "CNJ 114/330" in s


def test_format_progress_summary_tracking_uses_process():
    s = format_progress_summary(
        done=40,
        total=75,
        message="Atualizando 1020868-35.2019.4.01.3400",
        stage="tracking",
    )
    assert s == "Processo 41/75"


def test_eta_from_wall_clock_matches_pace():
    from datetime import datetime, timedelta, timezone

    from monitor_jus.progress import eta_from_wall_clock

    now = datetime(2026, 8, 9, 22, 20, tzinfo=timezone.utc)
    started = now - timedelta(minutes=12)
    hb = now - timedelta(seconds=30)
    eta = eta_from_wall_clock(
        done=40,
        total=75,
        started_at=started,
        now=now,
        heartbeat_at=hb,
    )
    # 40 em 12 min → ~18s/item → 35 restantes ≈ 10.5 min
    assert eta is not None
    assert 9 * 60 < eta < 12 * 60


def test_eta_from_wall_clock_none_when_heartbeat_stale():
    from datetime import datetime, timedelta, timezone

    from monitor_jus.progress import eta_from_wall_clock

    now = datetime(2026, 8, 9, 22, 20, tzinfo=timezone.utc)
    eta = eta_from_wall_clock(
        done=40,
        total=75,
        started_at=now - timedelta(minutes=12),
        now=now,
        heartbeat_at=now - timedelta(minutes=10),
        stale_after_seconds=120,
    )
    assert eta is None


def test_report_without_bind_is_noop():
    clear_job()
    assert report(stage="x", done=1, total=2, force=True) is None


def test_report_computes_pct(monkeypatch, tmp_path):
    clear_job()
    # evita tocar DB real em persist
    monkeypatch.setattr("monitor_jus.progress._persist", lambda *a, **k: None)
    bind_job("job-test", "run-test")
    snap = report(stage="discovery", done=1, total=4, message="passo", force=True)
    assert snap is not None
    assert snap["progress_pct"] == 25
    assert snap["bar"].startswith("[")
    assert snap["eta"]  # label não vazio (ex.: 0s / — / 1m …)
    assert "eta_seconds" in snap
    clear_job()
