from datetime import date, timedelta

from monitor_jus.config import Settings
from monitor_jus.pipeline.discovery import _historical_window, _resolve_window


def test_historical_window_uses_lookback_days(monkeypatch):
    settings = Settings(djen_historical_lookback_days=30)
    monkeypatch.setattr(
        "monitor_jus.pipeline.discovery.load_ops",
        lambda _s=None: {"discovery": {"lookback_days": 1095}, "bootstrap": {}, "poll": {}},
    )
    start, until = _historical_window(settings, purpose="discovery")
    assert until == date.today()
    assert start == until - timedelta(days=1095)


def test_resolve_window_historical_much_longer_than_incremental(monkeypatch):
    settings = Settings(djen_overlap_hours=48, djen_historical_lookback_days=365)
    monkeypatch.setattr(
        "monitor_jus.pipeline.discovery.load_fontes",
        lambda _s: {"djen": {"overlap_hours": 48, "historical_lookback_days": 365}},
    )
    monkeypatch.setattr(
        "monitor_jus.pipeline.discovery.load_ops",
        lambda _s=None: {
            "discovery": {"lookback_days": 365},
            "bootstrap": {"lookback_days": 365},
            "poll": {"overlap_hours": 48},
        },
    )

    class _FakeSession:
        def scalar(self, *_a, **_k):
            return None

    start, until = _resolve_window(settings, _FakeSession(), mode="historical")
    assert (until - start).days == 365

    start_i, until_i = _resolve_window(settings, _FakeSession(), mode="incremental")
    assert (until_i - start_i).days == 2