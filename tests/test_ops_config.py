from monitor_jus.ops_config import _sanitize, load_ops, save_ops


def test_sanitize_clamps_and_bools():
    cleaned = _sanitize(
        {
            "discovery": {
                "lookback_days": "99999",
                "max_pages": "2",
                "search_oabs": "on",
                "search_names": 0,
            },
            "bootstrap": {"complete_missing_capa": "sim"},
        }
    )
    assert cleaned["discovery"]["lookback_days"] == 3650
    assert cleaned["discovery"]["max_pages"] == 5
    assert cleaned["discovery"]["search_oabs"] is True
    assert cleaned["discovery"]["search_names"] is False
    assert cleaned["bootstrap"]["complete_missing_capa"] is True


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    from monitor_jus.config import Settings

    settings = Settings(config_dir=str(tmp_path))
    path = save_ops(
        {
            "discovery": {"lookback_days": 400, "search_oabs": True, "search_names": False},
            "bootstrap": {"lookback_days": 500, "complete_missing_capa": True},
        },
        settings=settings,
    )
    assert path.exists()
    ops = load_ops(settings)
    assert ops["discovery"]["lookback_days"] == 400
    assert ops["discovery"]["search_names"] is False
    assert ops["bootstrap"]["lookback_days"] == 500
