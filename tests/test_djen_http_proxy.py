"""DJEN_HTTP_PROXY é repassado ao cliente HTTP."""

from __future__ import annotations

from monitor_jus.config import Settings
from monitor_jus.sources.djen.client import DjenClient, _proxy_hint


def test_proxy_hint_masks_credentials():
    assert _proxy_hint("http://user:pass@100.64.1.2:8899") == "100.64.1.2:8899"
    assert _proxy_hint("") is None


def test_djen_client_sets_http_proxy(monkeypatch):
    settings = Settings(
        djen_enable=True,
        djen_http_proxy="http://100.64.1.2:8899",
    )
    client = DjenClient(settings)
    assert client.http.proxy == "http://100.64.1.2:8899"
    assert client.health()["http_proxy"] == "100.64.1.2:8899"
