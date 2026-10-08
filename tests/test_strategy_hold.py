import pytest

from bench.config import Asset
from bench.costs import Costs
from bench.strategies import hold
from tests.helpers import candles

A = [Asset("AAA", "stock", 5, 0.002, 0.0), Asset("CCC", "crypto", 0, 0.002, 0.0)]


def px():
    return {"AAA": candles([
        ("2026-01-05", 100, 100, 100, 100),
        ("2026-01-06", 100, 103, 99, 102),
        ("2026-01-07", 103, 105, 102, 104),
        ("2026-01-08", 105, 106, 102, 103),
    ])}


def P(pairs, asset="AAA"):
    return {(asset, asof): {"asof": asof, "expected_return": e, "path": None} for asof, e in pairs}


def test_three_day_hold_pays_cost_only_on_entry_and_exit():
    # enter 01-06, keep 01-07 (still positive), sell at the 01-08 open (turned negative)
    r = hold.hold(P([("2026-01-05", 0.01), ("2026-01-06", 0.0005), ("2026-01-07", -0.01)]), px(), Costs(A), 10000.0)
    acts = [(x["date"], x["action"]) for x in r.ledger]
    assert acts == [("2026-01-06", "open"), ("2026-01-07", "hold"), ("2026-01-08", "close")]
    nets = [x["net_ret"] for x in r.ledger]
    assert nets[0] == pytest.approx(102 / 100 - 1 - 0.001)
    assert nets[1] == pytest.approx(104 / 102 - 1)
    assert nets[2] == pytest.approx(105 / 104 - 1 - 0.001)
    want = 10000.0 * (1 + nets[0]) * (1 + nets[1]) * (1 + nets[2])
    assert r.equity[-1]["equity"] == pytest.approx(want)
    assert [e["n_traded"] for e in r.equity] == [1, 0, 1]
    assert [e["n_open"] for e in r.equity] == [1, 1, 0]
    assert r.positions == []


def test_weak_positive_call_does_not_open_but_keeps():
    # 0.0005 is below the 0.002 cost: no entry on its own
    r = hold.hold(P([("2026-01-05", 0.0005)]), px(), Costs(A), 10000.0)
    assert [(x["action"], x["traded"]) for x in r.ledger] == [("none", 0)]


def test_missing_prediction_sells_at_next_open():
    # the model predicts once, then stops: the position must not be held forever
    r = hold.hold(P([("2026-01-05", 0.01)]), px(), Costs(A), 10000.0)
    assert [(x["date"], x["action"]) for x in r.ledger] == [("2026-01-06", "open"), ("2026-01-07", "close")]
    assert r.ledger[1]["net_ret"] == pytest.approx(103 / 102 - 1 - 0.001)
    assert r.positions == []


def test_open_position_is_reported():
    r = hold.hold(P([("2026-01-05", 0.01), ("2026-01-06", 0.01), ("2026-01-07", 0.01)]), px(), Costs(A), 10000.0)
    pos = r.positions[0]
    assert pos["asset"] == "AAA" and pos["entry_date"] == "2026-01-06" and pos["entry"] == 100.0
    assert pos["last_date"] == "2026-01-08" and pos["last"] == 103.0
    assert pos["unrealised"] == pytest.approx(103 / 100 - 1 - 0.001)


def test_position_carried_over_days_without_a_candle():
    # AAA has no candle on the 7th (holiday); CCC trades every day. AAA is carried, no row, then kept.
    prices = {
        "AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102), ("2026-01-08", 105, 106, 102, 103)]),
        "CCC": candles([("2026-01-05", 10, 10, 10, 10), ("2026-01-06", 10, 10, 10, 10), ("2026-01-07", 10, 10, 10, 10), ("2026-01-08", 10, 10, 10, 10)]),
    }
    preds = P([("2026-01-05", 0.01), ("2026-01-06", 0.01)])
    r = hold.hold(preds, prices, Costs(A), 10000.0)
    aaa = [(x["date"], x["action"]) for x in r.ledger if x["asset"] == "AAA"]
    assert aaa == [("2026-01-06", "open"), ("2026-01-08", "hold")]
    assert [x for x in r.ledger if x["asset"] == "AAA"][1]["net_ret"] == pytest.approx(103 / 102 - 1)


def test_always_long_buys_once_and_holds():
    r = hold.hold(P([("2026-01-05", 1.0), ("2026-01-06", 1.0), ("2026-01-07", 1.0)]), px(), Costs(A), 10000.0)
    assert [x["action"] for x in r.ledger] == ["open", "hold", "hold"]
    assert sum(x["cost"] for x in r.ledger) == pytest.approx(0.001)


def test_future_candles_do_not_change_past_decisions():
    import pandas as pd
    preds = P([("2026-01-05", 0.01), ("2026-01-06", 0.0005), ("2026-01-07", -0.01)])
    base = hold.hold(preds, px(), Costs(A), 10000.0)
    later = px()
    later["AAA"] = pd.concat([later["AAA"], candles([("2026-01-09", 900, 900, 900, 900)])], ignore_index=True)
    again = hold.hold(preds, later, Costs(A), 10000.0)
    assert again.ledger[: len(base.ledger)] == base.ledger
