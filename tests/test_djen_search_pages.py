"""Metadados de paginação DJEN (hit_max_pages)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from monitor_jus.sources.djen.client import DjenClient
from monitor_jus.sources.djen.criteria import DjenSearchCriteria


def test_search_all_pages_hit_max_pages():
    client = DjenClient.__new__(DjenClient)
    client.settings = MagicMock()
    page_calls = {"n": 0}

    def fake_search(criteria):
        page_calls["n"] += 1
        # Página cheia (size=2) e total alto → ainda há mais páginas
        return {
            "items": [{"id": f"a{page_calls['n']}-1"}, {"id": f"a{page_calls['n']}-2"}],
            "total": 100,
        }

    client.search = fake_search  # type: ignore[method-assign]
    criteria = DjenSearchCriteria(
        oab_number="123",
        oab_state="SP",
        available_from=date(2026, 1, 1),
        available_until=date(2026, 1, 31),
        size=2,
        page=1,
    )
    result = client.search_all_pages(criteria, max_pages=2)
    assert result["hit_max_pages"] is True
    assert result["pages_fetched"] == 2
    assert len(result["items"]) == 4


def test_search_all_pages_no_saturation_when_exhausted():
    client = DjenClient.__new__(DjenClient)
    client.settings = MagicMock()

    def fake_search(criteria):
        return {"items": [{"id": "only"}], "total": 1}

    client.search = fake_search  # type: ignore[method-assign]
    criteria = DjenSearchCriteria(
        lawyer_name="Fulano",
        available_from=date(2026, 1, 1),
        available_until=date(2026, 1, 31),
        size=50,
        page=1,
    )
    result = client.search_all_pages(criteria, max_pages=5)
    assert result["hit_max_pages"] is False
    assert result["pages_fetched"] == 1
    assert len(result["items"]) == 1
