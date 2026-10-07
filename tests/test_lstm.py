import pytest

pytest.importorskip("torch")

import pandas as pd  # noqa: E402

from bench.config import Settings  # noqa: E402
from bench.runner import run_estimator_day  # noqa: E402
from bench.store import Store  # noqa: E402
from estimators.lstm import predict as lp  # noqa: E402
from tests.helpers import random_walk  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_memo():
    lp._MEMO.clear()
    yield
    lp._MEMO.clear()


def _hist(n=200):
    return {"A": random_walk(n, seed=1), "B": random_walk(n, seed=2)}


def test_boundary_is_the_monday_on_or_before():
    assert lp._boundary("2024-03-04") == "2024-03-04"  # a Monday
    assert lp._boundary("2024-03-10") == "2024-03-04"  # the Sunday after it
    assert lp._boundary("2024-03-11") == "2024-03-11"


def test_training_itself_is_deterministic():
    h = _hist()
    first = lp.Lstm().predict(h, ["A", "B"])
    lp._MEMO.clear()  # force a real retrain, not a memo hit
    assert lp.Lstm().predict(h, ["A", "B"]) == first


def test_model_ignores_candles_after_the_weekly_boundary():
    h = _hist()
    asof = max(df["date"].iloc[-1] for df in h.values())
    boundary = lp._boundary(asof)
    altered = {a: df.copy() for a, df in h.items()}
    for df in altered.values():
        late = df["date"] > boundary
        df.loc[late, ["open", "high", "low", "close"]] *= 1.7  # a different future
    ref = lp._model(h, asof)
    lp._MEMO.clear()
    other = lp._model(altered, asof)
    for p, q in zip(ref.parameters(), other.parameters()):
        assert bool((p == q).all()), "weights depend on candles after the boundary"


def test_model_is_reused_within_a_week_and_retrained_in_the_next():
    h = _hist(210)
    d = h["A"]["date"]
    mon = [x for x in d if pd.Timestamp(x).weekday() == 0][-3]  # a Monday with later data
    week = lambda day: {a: df[df["date"] <= day].reset_index(drop=True) for a, df in h.items()}  # noqa: E731
    tue = (pd.Timestamp(mon) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    nxt = (pd.Timestamp(mon) + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    m1 = lp._model(week(mon), mon)
    assert lp._model(week(tue), tue) is m1  # same week, same training data: reused
    assert lp._model(week(nxt), nxt) is not m1  # next week: retrained on more history


def test_runner_prediction_does_not_depend_on_future_candles(tmp_path):
    full = _hist(230)
    run_date = full["A"]["date"].iloc[200]  # predict at this date from candles dated before it
    future_changed = {a: df.copy() for a, df in full.items()}
    for df in future_changed.values():
        late = df["date"] >= run_date
        df.loc[late, ["open", "high", "low", "close"]] *= 0.5
    got = []
    for i, prices in enumerate((full, future_changed)):
        lp._MEMO.clear()
        st = Store(tmp_path / str(i))
        rec = run_estimator_day(st, lp.Lstm(), prices, run_date, Settings())
        assert rec["status"] == "ok"
        got.append(st.load_predictions("lstm")[run_date]["predictions"])
    assert got[0] == got[1] and got[0]


def test_too_little_history_gives_no_prediction():
    assert lp.Lstm().predict({"A": random_walk(lp.MIN_ROWS - 1)}, ["A"]) == {}
