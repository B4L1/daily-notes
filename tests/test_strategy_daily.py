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


def test_short_earns_when_the_price_falls():
    # BBB falls 50 -> 49: gross -0.02. cost 0.0001 + borrow 0.36/360 = 0.001
    r = daily.one_day_short(preds(BBB=-0.01), px(), Costs(A), 10000.0)
    row = r.ledger[0]
    assert row["side"] == "short" and row["traded"] == 1 and row["hit"] == 1
    assert row["net_ret"] == pytest.approx(0.02 - 0.0001 - 0.001)
    assert row["cost"] == pytest.approx(0.0011)


def test_short_loses_when_the_price_rises():
    r = daily.one_day_short(preds(AAA=-0.01), px(), Costs(A), 10000.0)
    assert r.ledger[0]["net_ret"] == pytest.approx(-0.02 - 0.001 - 0.001)


def test_short_account_still_goes_long_on_up_calls():
    r = daily.one_day_short(preds(AAA=0.01), px(), Costs(A), 10000.0)
    assert r.ledger[0]["side"] == "long" and r.ledger[0]["net_ret"] == pytest.approx(0.019)


def test_small_down_call_does_not_short():
    r = daily.one_day_short(preds(AAA=-0.0005), px(), Costs(A), 10000.0)
    assert r.ledger[0]["traded"] == 0


def test_long_only_account_ignores_down_calls():
    assert daily.one_day(preds(BBB=-0.01), px(), Costs(A), 10000.0).ledger[0]["traded"] == 0


def four():
    assets = [Asset(s, "stock", 5, 0.001, 0.0) for s in ("A1", "A2", "A3", "A4")]
    prices = {s: candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 101, 99, 101)]) for s in ("A1", "A2", "A3", "A4")}
    return assets, prices


def test_top_picks_takes_the_three_strongest():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None}
         for s, e in (("A1", 0.01), ("A2", 0.04), ("A3", 0.02), ("A4", 0.03))}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert sorted(x["asset"] for x in r.ledger if x["traded"]) == ["A2", "A3", "A4"]
    assert len(r.ledger) == 4  # the unpicked call still gets a row


def test_top_picks_with_fewer_than_three_qualifying():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None}
         for s, e in (("A1", 0.01), ("A2", 0.0005), ("A3", -0.02), ("A4", 0.0))}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert [x["asset"] for x in r.ledger if x["traded"]] == ["A1"]


def test_top_picks_ties_break_by_symbol():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.01, "path": None} for s in ("A1", "A2", "A3", "A4")}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert sorted(x["asset"] for x in r.ledger if x["traded"]) == ["A1", "A2", "A3"]


def test_top_picks_ties_on_expected_return_break_by_confidence_then_symbol():
    assets, prices = four()
    conf = {"A1": 0.5, "A2": 1.0, "A3": 0.75, "A4": 0.6}
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": 1.0, "confidence": conf[s], "path": None}
         for s in conf}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert sorted(x["asset"] for x in r.ledger if x["traded"]) == ["A2", "A3", "A4"]


def test_missing_confidence_ranks_after_any_confidence_on_a_tie():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.01, "confidence": c, "path": None}
         for s, c in (("A1", None), ("A2", 0.1), ("A3", None), ("A4", 0.2))}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert sorted(x["asset"] for x in r.ledger if x["traded"]) == ["A1", "A2", "A4"]


def three():
    assets = [Asset("A1", "stock", 5, 0.001, 0.0), Asset("A2", "stock", 5, 0.001, 0.0), Asset("A3", "stock", 5, 0.001, 0.0)]
    prices = {
        "A1": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 104, 99, 104)]),  # +4%
        "A2": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 101, 98, 98)]),   # -2%
        "A3": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 110, 99, 110)]),  # +10%
    }
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None}
         for s, e in (("A1", 0.031), ("A2", 0.011), ("A3", 0.0005))}
    return assets, prices, p


def test_full_equal_invests_the_whole_account_in_the_qualifying_calls():
    assets, prices, p = three()
    r = daily.full_equal(p, prices, Costs(assets), 10000.0)
    # A1 and A2 qualify, half each: (0.039 - 0.021) / 2
    assert r.equity[0]["day_return"] == pytest.approx((0.04 - 0.001) / 2 + (-0.02 - 0.001) / 2)
    assert {x["asset"]: x["traded"] for x in r.ledger} == {"A1": 1, "A2": 1, "A3": 0}
    # one_day leaves a third in cash on the same calls
    assert daily.one_day(p, prices, Costs(assets), 10000.0).equity[0]["day_return"] == pytest.approx((0.039 - 0.021) / 3)


def test_full_weighted_sizes_by_expected_gain_after_costs():
    assets, prices, p = three()
    r = daily.full_weighted(p, prices, Costs(assets), 10000.0)
    # edges 0.030 and 0.010 -> shares 0.75 and 0.25
    assert r.equity[0]["day_return"] == pytest.approx(0.75 * 0.039 + 0.25 * -0.021)
    shares = {x["asset"]: x["weight"] / 3 for x in r.ledger if x["traded"]}
    assert shares == pytest.approx({"A1": 0.75, "A2": 0.25})


def test_all_in_puts_everything_on_the_strongest_call():
    assets, prices, p = three()
    r = daily.all_in(p, prices, Costs(assets), 10000.0)
    assert [x["asset"] for x in r.ledger if x["traded"]] == ["A1"]
    assert r.equity[0]["day_return"] == pytest.approx(0.039) and r.equity[0]["equity"] == pytest.approx(10390.0)


def test_strongest_is_judged_after_costs():
    assets = [Asset("CHEAP", "etf", 5, 0.0001, 0.0), Asset("DEAR", "crypto", 5, 0.01, 0.0)]
    prices = {s: candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 101, 99, 101)]) for s in ("CHEAP", "DEAR")}
    p = {("CHEAP", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.008, "path": None},
         ("DEAR", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.012, "path": None}}
    r = daily.all_in(p, prices, Costs(assets), 10000.0)
    assert [x["asset"] for x in r.ledger if x["traded"]] == ["CHEAP"]


def test_fully_invested_accounts_stay_in_cash_when_nothing_qualifies():
    assets, prices, _ = three()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": -0.01, "path": None} for s in ("A1", "A2", "A3")}
    for fn in (daily.full_equal, daily.full_weighted, daily.all_in):
        r = fn(p, prices, Costs(assets), 10000.0)
        assert r.equity[0]["equity"] == 10000.0 and len(r.ledger) == 3 and not any(x["traded"] for x in r.ledger)
