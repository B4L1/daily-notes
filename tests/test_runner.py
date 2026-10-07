import json
import math
from datetime import datetime, timezone

import pytest

from bench.config import Settings
from bench.runner import (
    assets_needing_prediction, cut_history, cutoff_for, live_window_ok, run_estimator_day,
)
from bench.store import Store
from estimators.base import Estimator, Prediction
from tests.helpers import candles, random_walk

S = Settings()


class Spy(Estimator):
    name = "spy"

    def __init__(self):
        self.seen = {}
        self.asked = []

    def predict(self, history, assets):
        self.seen = {a: df["date"].max() for a, df in history.items() if len(df)}
        self.asked = list(assets)
        return {a: Prediction(0.01) for a in assets if len(history[a])}


class Bad(Estimator):
    name = "bad"

    def __init__(self, value):
        self.value = value

    def predict(self, history, assets):
        return {a: Prediction(self.value) for a in assets if len(history[a])}


class Boom(Estimator):
    name = "boom"

    def predict(self, history, assets):
        raise RuntimeError("model exploded")


class Extra(Estimator):
    name = "extra"

    def predict(self, history, assets):
        return {"NOT_ASKED": Prediction(0.5), **{a: Prediction(0.01) for a in assets if len(history[a])}}


def test_cutoff_is_the_day_before():
    assert cutoff_for("2026-01-06") == "2026-01-05"


def test_estimator_never_sees_the_run_day_or_later(tmp_path):
    prices = {"AAA": candles([
        ("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1),
        ("2026-01-06", 1, 1, 1, 1),  # today's partial candle: must be invisible
        ("2026-01-07", 1, 1, 1, 1),
    ])}
    spy = Spy()
    run_estimator_day(Store(tmp_path), spy, prices, "2026-01-06", S)
    assert spy.seen == {"AAA": "2026-01-05"}


def test_prediction_is_saved_with_asof(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    rec = run_estimator_day(st, Spy(), prices, "2026-01-06", S)
    assert rec["status"] == "ok" and rec["n_predictions"] == 1
    saved = st.load_predictions("spy")["2026-01-06"]["predictions"]["AAA"]
    assert saved["asof"] == "2026-01-05" and saved["expected_return"] == 0.01


def test_rerun_same_day_is_idempotent(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": random_walk(30, "2026-01-01")}
    run_estimator_day(st, Spy(), prices, "2026-01-31", S)
    first = json.dumps(st.load_predictions("spy"), sort_keys=True)
    run_estimator_day(st, Spy(), prices, "2026-01-31", S)
    assert json.dumps(st.load_predictions("spy"), sort_keys=True) == first


def test_weekend_stock_is_not_repredicted_but_crypto_is(tmp_path):
    # 2026-01-02 is a Friday. STK has no weekend candles; CRY trades every day.
    stk = candles([("2025-12-31", 1, 1, 1, 1), ("2026-01-02", 1, 1, 1, 1)])
    cry = candles([("2026-01-01", 1, 1, 1, 1), ("2026-01-02", 1, 1, 1, 1), ("2026-01-03", 1, 1, 1, 1)])
    prices = {"STK": stk, "CRY": cry}
    st = Store(tmp_path)
    sat, sun = Spy(), Spy()
    run_estimator_day(st, sat, prices, "2026-01-03", S)   # Saturday: cutoff Friday
    assert sorted(sat.asked) == ["CRY", "STK"]
    run_estimator_day(st, sun, prices, "2026-01-04", S)   # Sunday: cutoff Saturday
    assert sun.asked == ["CRY"]


def test_non_finite_output_is_a_recorded_failure_with_no_prediction(tmp_path):
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    for value in (math.nan, math.inf):
        st = Store(tmp_path / str(value))
        rec = run_estimator_day(st, Bad(value), prices, "2026-01-06", S)
        assert rec["status"] == "failed" and "non-finite" in rec["error"]
        assert st.load_predictions("bad") == {}
        assert st.load_runs("bad")[-1]["status"] == "failed"


def test_exception_is_recorded_not_raised(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1)])}
    rec = run_estimator_day(st, Boom(), prices, "2026-01-06", S)
    assert rec["status"] == "failed" and "model exploded" in rec["error"]
    assert st.load_predictions("boom") == {}


def test_assets_nobody_asked_for_are_ignored(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    run_estimator_day(st, Extra(), prices, "2026-01-06", S)
    assert list(st.load_predictions("extra")["2026-01-06"]["predictions"]) == ["AAA"]


def test_live_window():
    d = "2026-01-06"
    ok = datetime(2026, 1, 6, 0, 40, tzinfo=timezone.utc)
    ok_late = datetime(2026, 1, 6, 11, 59, tzinfo=timezone.utc)
    late = datetime(2026, 1, 6, 12, 1, tzinfo=timezone.utc)
    early = datetime(2026, 1, 5, 23, 0, tzinfo=timezone.utc)
    assert live_window_ok(d, ok) and live_window_ok(d, ok_late)
    assert not live_window_ok(d, late) and not live_window_ok(d, early)


def test_late_run_settles_but_does_not_predict(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    late = datetime(2026, 1, 6, 13, 0, tzinfo=timezone.utc)
    rec = run_estimator_day(st, Spy(), prices, "2026-01-06", S, now=late)
    assert rec["status"] == "skipped_late"
    assert st.load_predictions("spy") == {}


def test_settles_incrementally_across_runs(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([
        ("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102),
    ])}
    run_estimator_day(st, Spy(), prices, "2026-01-03", S)   # predicts for the 5th
    run_estimator_day(st, Spy(), prices, "2026-01-06", S)   # settles the 5th
    assert len(st.load_equity("spy")) == 1
    assert st.load_equity("spy")["equity"].iloc[0] == pytest.approx(10190.0)


class Flaky(Estimator):
    name = "flaky"

    def __init__(self):
        self.calls = 0
        self.asked = []

    def predict(self, history, assets):
        self.calls += 1
        self.asked = list(assets)
        return {a: Prediction(0.001 * self.calls) for a in assets if len(history[a])}


def test_late_run_still_settles_before_skipping(tmp_path):
    st = Store(tmp_path)
    st.save_prediction("spy", "2026-01-03", {"predictions": {
        "AAA": {"asof": "2026-01-02", "expected_return": 0.01, "confidence": None, "path": None}}})
    prices = {"AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)])}
    late = datetime(2026, 1, 6, 13, 0, tzinfo=timezone.utc)
    rec = run_estimator_day(st, Spy(), prices, "2026-01-06", S, now=late)
    assert rec["status"] == "skipped_late"
    assert st.load_equity("spy")["equity"].iloc[0] == pytest.approx(10190.0)
    assert "2026-01-06" not in st.load_predictions("spy")


def test_rerun_with_nondeterministic_estimator_keeps_first_file(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    est = Flaky()
    run_estimator_day(st, est, prices, "2026-01-06", S)
    first = json.dumps(st.load_predictions("flaky"), sort_keys=True)
    rec = run_estimator_day(st, est, prices, "2026-01-06", S)
    assert est.calls == 1 and rec["status"] == "ok" and rec["n_predictions"] == 1
    assert json.dumps(st.load_predictions("flaky"), sort_keys=True) == first


def test_failing_rerun_leaves_existing_file_and_records_failure(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    run_estimator_day(st, Spy(), prices, "2026-01-06", S)
    first = json.dumps(st.load_predictions("spy"), sort_keys=True)
    prices["BBB"] = candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])

    class SpyBoom(Boom):
        name = "spy"

    rec = run_estimator_day(st, SpyBoom(), prices, "2026-01-06", S)
    assert rec["status"] == "failed"
    assert st.load_runs("spy")[-1]["status"] == "failed"
    assert json.dumps(st.load_predictions("spy"), sort_keys=True) == first


def test_rerun_adds_newly_available_asset_and_asks_only_for_it(tmp_path):
    st = Store(tmp_path)
    a = candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])
    run_estimator_day(st, Flaky(), {"AAA": a, "BBB": candles([("2026-01-06", 1, 1, 1, 1)])}, "2026-01-06", S)
    first_a = st.load_predictions("flaky")["2026-01-06"]["predictions"]["AAA"]
    est = Flaky()
    est.calls = 5
    prices = {"AAA": a, "BBB": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    rec = run_estimator_day(st, est, prices, "2026-01-06", S)
    preds = st.load_predictions("flaky")["2026-01-06"]["predictions"]
    assert est.asked == ["BBB"] and rec["n_predictions"] == 2
    assert preds["AAA"] == first_a and preds["BBB"]["expected_return"] == pytest.approx(0.006)


def test_live_rerun_keeps_created_at(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    t1 = datetime(2026, 1, 6, 0, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 6, 0, 40, tzinfo=timezone.utc)
    run_estimator_day(st, Spy(), prices, "2026-01-06", S, now=t1)
    run_estimator_day(st, Spy(), prices, "2026-01-06", S, now=t2)
    assert st.load_predictions("spy")["2026-01-06"]["created_at"] == t1.isoformat()


@pytest.mark.parametrize("pred", [
    Prediction(0.01, confidence=math.nan),
    Prediction(0.01, path=[1.0, math.inf]),
])
def test_non_finite_confidence_or_path_is_a_recorded_failure(tmp_path, pred):
    class Fixed(Estimator):
        name = "fixed"

        def predict(self, history, assets):
            return {a: pred for a in assets}

    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    rec = run_estimator_day(st, Fixed(), prices, "2026-01-06", S)
    assert rec["status"] == "failed" and "non-finite" in rec["error"]
    assert st.load_predictions("fixed") == {}
