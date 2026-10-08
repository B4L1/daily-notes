import pytest

from bench.config import Asset, load_config
from bench.costs import Costs


def test_costs_per_asset():
    c = Costs([Asset("SPY", "etf", 5, 0.0001, 0.005), Asset("BTC-USD", "crypto", 0, 0.0025, 0.36)])
    assert c.round_trip("SPY") == 0.0001 and c.half("SPY") == 0.00005
    assert c.round_trip("BTC-USD") == 0.0025
    assert c.borrow_day("BTC-USD") == pytest.approx(0.001)
    assert c.group("SPY") == "etf"


def test_unknown_symbol_is_an_error():
    with pytest.raises(KeyError):
        Costs([]).round_trip("NOPE")


def test_repo_config_has_a_cost_for_every_asset():
    _, assets = load_config("assets.yaml")
    groups = {a.symbol: a.group for a in assets}
    assert groups["SPY"] == "etf" and groups["QQQ"] == "etf" and groups["AAPL"] == "stock"
    by_group = {a.group: a for a in assets}
    assert by_group["etf"].cost_round_trip == 0.0001
    assert by_group["stock"].cost_round_trip == 0.0005
    assert by_group["commodity"].cost_round_trip == 0.0003
    assert by_group["crypto"].cost_round_trip == 0.0025
    assert by_group["crypto"].borrow_annual == 0.10 and by_group["stock"].borrow_annual == 0.005


def test_bad_group_or_cost_is_rejected(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("assets:\n  - {symbol: X, group: bond, max_gap_days: 5}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="group"):
        load_config(p)
    p.write_text("assets:\n  - {symbol: X, group: stock, max_gap_days: 5, cost_round_trip: -0.1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cost"):
        load_config(p)
