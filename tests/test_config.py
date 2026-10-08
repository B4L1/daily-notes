from pathlib import Path

import pytest

from bench.config import Asset, load_config

ROOT = Path(__file__).resolve().parent.parent


def test_real_config_loads():
    settings, assets = load_config(ROOT / "assets.yaml")
    assert len(assets) == 21
    assert settings.start_equity == 10000
    assert Asset("BTC-USD", "crypto", 0, 0.0025, 0.10) in assets


def test_unknown_setting_rejected(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("settings: {bogus: 1}\nassets: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        load_config(p)


def test_duplicate_symbol_rejected(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text(
        "assets:\n  - {symbol: A, group: stock, max_gap_days: 5}\n"
        "  - {symbol: A, group: stock, max_gap_days: 5}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_config(p)


def test_cost_settings_are_gone():
    from bench.config import Settings
    assert not hasattr(Settings(), "cost_round_trip") and not hasattr(Settings(), "trade_threshold")
