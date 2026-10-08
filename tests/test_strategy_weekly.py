import pytest

from bench.config import Asset
from bench.costs import Costs
from bench.strategies import weekly
from tests.helpers import candles

A = [Asset("AAA", "stock", 5, 0.002, 0.0)]
# session: 0       1        2        3        4        5        6
OPEN = [100, 100, 102, 103, 101, 104, 106]
CLOSE = [100, 102, 103, 101, 104, 106, 105]
DATES = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]


def px():
    return {"AAA": candles([(d, o, max(o, c), min(o, c), c) for d, o, c in zip(DATES, OPEN, CLOSE)])}


def P(asof, last, exp5):
    return {("AAA", asof): {"asof": asof, "expected_return": 0.0, "path": [last] * 4 + [last * (1 + exp5)]}}


def test_one_slot_runs_five_sessions():
    r = weekly.weekly(P("2026-01-05", 100.0, 0.05), px(), Costs(A), 10000.0)
    acts = [(x["date"], x["action"]) for x in r.ledger]
    assert acts == [(DATES[1], "open"), (DATES[2], "hold"), (DATES[3], "hold"), (DATES[4], "hold"), (DATES[5], "close")]
    nets = [x["net_ret"] for x in r.ledger]
    assert nets[0] == pytest.approx(102 / 100 - 1 - 0.001)
    assert nets[1] == pytest.approx(103 / 102 - 1)
    assert nets[4] == pytest.approx(106 / 104 - 1 - 0.001)
    assert all(x["weight"] == 0.2 for x in r.ledger)
    want = 10000.0
    for n in nets:
        want *= 1 + 0.2 * n
    assert r.equity[-1]["equity"] == pytest.approx(want)
    # 5-day call: predicted up, 106 vs 100 at the as-of close
    assert r.ledger[-1]["hit5"] == 1 and r.ledger[0]["hit5"] is None
    assert r.positions == []


def test_five_sessions_not_five_calendar_days():
    # opened Tuesday 01-06; the weekend has no candle; closes Monday 01-12 (its fifth session)
    r = weekly.weekly(P("2026-01-05", 100.0, 0.05), px(), Costs(A), 10000.0)
    assert r.ledger[-1]["date"] == "2026-01-12"


def test_weak_five_day_call_is_marked_but_not_traded():
    r = weekly.weekly(P("2026-01-05", 100.0, 0.001), px(), Costs(A), 10000.0)
    assert [(x["date"], x["action"], x["traded"]) for x in r.ledger] == [(DATES[1], "none", 0), (DATES[5], "mark", 0)]
    assert r.ledger[1]["hit5"] == 1 and r.ledger[1]["net_ret"] == 0.0


def test_down_call_is_marked_with_its_hit():
    r = weekly.weekly(P("2026-01-05", 100.0, -0.05), px(), Costs(A), 10000.0)
    assert r.ledger[-1]["action"] == "mark" and r.ledger[-1]["hit5"] == 0


def test_overlapping_slots_and_open_positions():
    preds = {**P("2026-01-05", 100.0, 0.05), **P("2026-01-06", 102.0, 0.05)}
    r = weekly.weekly(preds, px(), Costs(A), 10000.0)
    on_07 = [x for x in r.ledger if x["date"] == DATES[2]]
    assert sorted(x["action"] for x in on_07) == ["hold", "open"]
    # the second slot opens 01-07 and its fifth session is the last candle, so nothing is left open
    assert r.positions == []
    last = [x for x in r.ledger if x["date"] == DATES[6]]
    assert [x["action"] for x in last] == ["close"]


def test_open_slot_is_reported():
    r = weekly.weekly(P("2026-01-08", 101.0, 0.05), px(), Costs(A), 10000.0)
    assert r.positions[0]["entry_date"] == "2026-01-09" and r.positions[0]["last_date"] == "2026-01-13"
    assert r.equity[-1]["n_open"] == 1


def test_model_without_paths_has_no_weekly_account():
    p = {("AAA", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.5, "path": None}}
    assert weekly.weekly(p, px(), Costs(A), 10000.0) is None


def test_short_path_is_ignored():
    p = {("AAA", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.5, "path": [101.0, 102.0]}}
    assert weekly.weekly(p, px(), Costs(A), 10000.0) is None


def test_short_path_with_non_finite_value_is_ignored():
    for bad in (None, float("nan")):
        p = {("AAA", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.5,
                                     "path": [100.0, 100.0, 100.0, 100.0, bad]}}
        assert weekly.weekly(p, px(), Costs(A), 10000.0) is None


def test_n_open_counts_assets_without_a_candle_that_day():
    assets = [Asset("AAA", "stock", 5, 0.002, 0.0), Asset("BBB", "crypto", 5, 0.002, 0.0)]
    days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-10", "2026-01-11"]

    def frame(ds):
        return candles([(d, 100, 100, 100, 100) for d in ds])

    prices = {"AAA": frame(days[:5]), "BBB": frame(days)}  # the stock has no weekend candles

    def pred(asset, asof):
        return {(asset, asof): {"asof": asof, "expected_return": 0.0, "path": [100.0] * 4 + [105.0]}}

    preds = {**pred("AAA", days[0]), **pred("BBB", days[3])}
    r = weekly.weekly(preds, prices, Costs(assets), 10000.0)
    n_open = {x["date"]: x["n_open"] for x in r.equity}
    assert n_open[days[5]] == 2  # Saturday: the stock slot is still open though AAA has no candle
    assert n_open[days[6]] == 2
    assert r.equity[-1]["n_open"] == len(r.positions) == 2
