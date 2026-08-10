"""Discovery: resolução do nome da empresa não chama .get em str."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from monitor_jus.pipeline.discovery import search_company_nationally


def test_company_search_uses_label_when_meta_has_no_nome(monkeypatch):
    client = MagicMock()
    client.search_all_pages.return_value = {
        "items": [],
        "hit_max_pages": False,
        "pages_fetched": 1,
    }
    monkeypatch.setattr(
        "monitor_jus.pipeline.discovery._ingest_items",
        lambda *a, **k: {"received": 0, "created": 0, "updated": 0, "rejected": 0},
    )
    crit = SimpleNamespace(
        id="c1",
        label="Empresa Alpha Ltda",
        value="123",
        meta={"aliases": ["Alpha"]},
    )
    out = search_company_nationally(
        MagicMock(),
        client,
        crit,
        available_from=date(2026, 1, 1),
        available_until=date(2026, 8, 9),
        bootstrap_mode=False,
        settings=MagicMock(),
        max_pages=2,
    )
    assert "error" not in out
    # label + 1 alias
    assert client.search_all_pages.call_count == 2
