"""Links oficiais no digest: recalcula genéricos/inúteis."""

from __future__ import annotations

from types import SimpleNamespace

from monitor_jus.official_portal import resolve_official_link_result
from monitor_jus.report.html_report import render_digest_html


def test_tjsp_link_includes_cnj_search():
    link = resolve_official_link_result(
        "1071609-54.2022.8.26.0002",
        tribunal="TJSP",
        existing="https://esaj.tjsp.jus.br/cpopg/open.do",
    )
    assert link.url
    assert "search.do" in link.url or "show.do" in link.url
    assert "1071609" in link.url or "10716095420228260002" in link.url.replace("-", "").replace(".", "")
    assert link.link_type != "COURT_HOMEPAGE"


def test_digest_html_shows_change_date_and_fresh_link():
    ev = SimpleNamespace(
        official_link="https://esaj.tjsp.jus.br/cpopg/open.do",
        numero_cnj="1071609-54.2022.8.26.0002",
        tribunal="TJSP",
        event_type="MOVIMENTACAO_PROCESSUAL",
        priority="media",
        title="TJSP · Conclusão",
        summary=(
            "**O que aconteceu:** O processo foi concluso. "
            "**Processo afetado:** 1071609-54.2022.8.26.0002"
        ),
        description="O processo foi concluso.",
        tipo_movimentacao="Conclusão",
        possible_deadline_flag=False,
        requires_name_validation=False,
        criterion_refs=None,
        occurred_at=__import__("datetime").datetime(2026, 8, 1, 12, 0, tzinfo=__import__("datetime").timezone.utc),
        created_at=__import__("datetime").datetime(2026, 8, 9, 23, 0, tzinfo=__import__("datetime").timezone.utc),
        payload=None,
    )
    html = render_digest_html([ev], zero=False)  # type: ignore[arg-type]
    assert "Movimentação em" in html
    assert "01/08/2026" in html
    assert "open.do" not in html or "search.do" in html
    assert "1071609" in html
    assert "<strong>O que aconteceu:</strong>" in html
    assert "**O que aconteceu:**" not in html
