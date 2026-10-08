import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from bench.config import Asset, load_config
from bench.costs import Costs
from bench.data import load_prices
from bench.store import Store
from bench.strategies import common, daily
from tests.helpers import candles

A = [Asset("AAA", "stock", 5, 0.001, 0.36), Asset("BBB", "etf", 5, 0.0001, 0.36)]


def px():
    return {
        "AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102)]),
        "BBB": candles([("2026-01-05", 50, 50, 50, 50), ("2026-01-06", 50, 51, 49, 49)]),
    }


def preds(**exp):
    return {(a, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None} for a, e in exp.items()}


def test_long_trade_pays_the_assets_cost():
    r = daily.one_day(preds(AAA=0.01), px(), Costs(A), 10000.0)
    row = r.ledger[0]
    assert row["date"] == "2026-01-06" and row["action"] == "day" and row["side"] == "long"
    assert row["net_ret"] == pytest.approx(0.02 - 0.001) and row["traded"] == 1 and row["hit"] == 1
    assert row["group"] == "stock" and row["cost"] == pytest.approx(0.001)
    # two assets had a session, one traded: 0.019 / 2
    assert r.equity[0]["day_return"] == pytest.approx(0.0095)
    assert r.equity[0]["equity"] == pytest.approx(10095.0)
    assert r.equity[0]["n_universe"] == 2 and r.equity[0]["n_traded"] == 1
    assert r.positions == []


def test_threshold_is_the_assets_own_cost():
    # 0.0005 is below AAA's cost (0.001) and above BBB's (0.0001)
    r = daily.one_day(preds(AAA=0.0005, BBB=0.0005), px(), Costs(A), 10000.0)
    traded = {x["asset"]: x["traded"] for x in r.ledger}
    assert traded == {"AAA": 0, "BBB": 1}


def test_untraded_prediction_still_gets_a_row_and_a_hit():
    r = daily.one_day(preds(AAA=-0.01), px(), Costs(A), 10000.0)
    assert r.ledger[0]["traded"] == 0 and r.ledger[0]["net_ret"] == 0.0 and r.ledger[0]["hit"] == 0
    assert r.equity[0]["equity"] == 10000.0


def test_zero_expected_return_has_no_hit():
    r = daily.one_day(preds(AAA=0.0), px(), Costs(A), 10000.0)
    assert r.ledger[0]["hit"] is None


def test_prediction_without_a_next_candle_is_not_settled():
    p = {("AAA", "2026-01-06"): {"asof": "2026-01-06", "expected_return": 0.5, "path": None}}
    r = daily.one_day(p, px(), Costs(A), 10000.0)
    assert r.ledger == [] and r.equity == []


def test_future_candles_do_not_change_past_decisions():
    base = daily.one_day(preds(AAA=0.01), px(), Costs(A), 10000.0)
    later = px()
    later["AAA"] = pd.concat([later["AAA"], candles([("2026-01-07", 500, 500, 500, 500)])], ignore_index=True)
    again = daily.one_day(preds(AAA=0.01), later, Costs(A), 10000.0)
    assert again.ledger[: len(base.ledger)] == base.ledger and again.equity[: len(base.equity)] == base.equity


def test_index_predictions_later_run_date_wins():
    saved = {
        "2026-01-06": {"predictions": {"AAA": {"asof": "2026-01-05", "expected_return": 1.0}}},
        "2026-01-07": {"predictions": {"AAA": {"asof": "2026-01-05", "expected_return": 2.0}}},
    }
    assert common.index_predictions(saved)[("AAA", "2026-01-05")]["expected_return"] == 2.0


def test_flat_cost_reproduces_the_v1_equity_of_the_random_control():
    """The refactor changes nothing but the costs: under 0.1% everywhere, V1 comes back."""
    fixture = Path("tests/fixtures/v1_control_random_equity.csv")
    root = Path("data/backtest/estimators/control_random/predictions")
    if not fixture.exists() or not root.exists():
        pytest.skip("repo data not present")
    _, assets = load_config("assets.yaml")
    flat = [dataclasses.replace(a, cost_round_trip=0.001) for a in assets]
    prices = load_prices(Path("data/prices"), assets)
    saved = {f.stem: __import__("json").loads(f.read_text(encoding="utf-8")) for f in sorted(root.glob("*.json"))}
    r = daily.one_day(common.index_predictions(saved), prices, Costs(flat), 10000.0)
    want = pd.read_csv(fixture, dtype={"date": str})
    got = pd.DataFrame(r.equity).set_index("date").loc[want["date"]]
    assert (got["equity"].to_numpy() - want["equity"].to_numpy()).__abs__().max() < 1e-6
