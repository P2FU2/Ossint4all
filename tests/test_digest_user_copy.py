"""Textos do digest em linguagem de usuário."""

from __future__ import annotations

from monitor_jus.report.html_report import format_source_failures_for_user


def test_format_failures_aggregates_djen_403():
    failures = [
        {
            "source": "DJEN",
            "court": "TJSP",
            "job_type": "DIARY_SWEEP",
            "criterion": "—",
            "error": "DJEN 403/auth: djen auth failed: 403",
        },
        {
            "source": "DJEN",
            "court": "TJRJ",
            "job_type": "DIARY_SWEEP",
            "criterion": "—",
            "error": "DJEN 403/auth: djen auth failed: 403",
        },
        {
            "source": "DJEN",
            "court": "TRF3",
            "job_type": "DIARY_SWEEP",
            "criterion": "—",
            "error": "FailedAuthentication: CloudFront",
        },
    ]
    lines = format_source_failures_for_user(failures)
    assert len(lines) == 1
    assert "Diário da Justiça" in lines[0]
    assert "403" not in lines[0]
    assert "DIARY_SWEEP" not in lines[0]
    assert "3 tribunais" in lines[0]


def test_format_failures_empty():
    assert format_source_failures_for_user([]) == []
    assert format_source_failures_for_user(None) == []
