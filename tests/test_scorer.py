import pytest

from bench.config import Asset, Settings
from bench.scorer import models, score_store
from bench.store import Store
from tests.helpers import candles

ASSETS = [Asset("AAA", "stock", 5, 0.001, 0.0)]
REG = {
    "control_random": {"kind": "control"},
    "m1": {"kind": "ml"},
    "m2": {"kind": "ml"},
    "m3": {"kind": "ml"},
}


def px():
    return {"AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102), ("2026-01-07", 102, 104, 101, 103)])}


def save(store, model, exp, path=None):
    store.save_prediction(model, "2026-01-06", {
        "schema_version": 1, "estimator": model, "run_date": "2026-01-06", "created_at": None,
        "predictions": {"AAA": {"asof": "2026-01-05", "expected_return": exp, "confidence": None, "path": path}},
    })


def test_models_adds_the_ensemble():
    assert models(REG) == ["control_random", "m1", "m2", "m3", "ensemble"]


def test_scores_every_strategy_and_the_ensemble(tmp_path):
    st = Store(tmp_path)
    save(st, "control_random", -1.0)
    for m in ("m1", "m2", "m3"):
        save(st, m, 0.01)
    done = score_store(st, px(), ASSETS, Settings(), REG)
    assert done[("m1", "one_day")] == 1 and done[("m1", "hold")] == 2
    eq, led = st.load_account("m1", "one_day")
    assert eq["equity"].iloc[0] == pytest.approx(10190.0) and led["traded"].tolist() == [1]
    # the control does not vote: three up votes -> ensemble long
    assert st.load_predictions("ensemble")["2026-01-06"]["predictions"]["AAA"]["expected_return"] == 1.0
    assert st.load_account("ensemble", "one_day")[0]["equity"].iloc[0] == pytest.approx(10190.0)
    # the random control is scored too, under every strategy (it is each strategy's baseline)
    assert len(st.load_account("control_random", "one_day_short")[0]) == 1


def test_account_without_predictions_writes_nothing(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01)  # no path: no weekly account; m2, m3, control have no predictions at all
    done = score_store(st, px(), ASSETS, Settings(), REG)
    assert ("m1", "weekly") not in done and ("m2", "one_day") not in done
    assert not (tmp_path / "accounts" / "m1" / "weekly").exists()
    assert not (tmp_path / "accounts" / "m2").exists()
    eq, led = st.load_account("m2", "one_day")
    assert eq.empty and led.empty and st.load_positions("m2", "hold") == []


def test_scoring_twice_is_byte_identical_and_survives_deleted_positions(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01, path=[101, 102, 103, 104, 110])
    score_store(st, px(), ASSETS, Settings(), REG)
    files = sorted(p for p in (tmp_path / "accounts").rglob("*") if p.is_file())
    first = {p: p.read_bytes() for p in files}
    (tmp_path / "accounts" / "m1" / "hold" / "positions.json").unlink()
    score_store(st, px(), ASSETS, Settings(), REG)
    assert {p: p.read_bytes() for p in files} == first


def test_stale_account_files_are_removed(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01)
    score_store(st, px(), ASSETS, Settings(), REG)
    for f in (tmp_path / "estimators" / "m1" / "predictions").glob("*.json"):
        f.unlink()
    score_store(st, px(), ASSETS, Settings(), REG)
    assert not (tmp_path / "accounts" / "m1" / "one_day" / "equity.csv").exists()


def test_non_finite_result_fails_loudly_and_writes_nothing(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01)
    bad = px()
    bad["AAA"].loc[1, "close"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        score_store(st, bad, ASSETS, Settings(), REG)
    assert not (tmp_path / "accounts" / "m1" / "one_day" / "equity.csv").exists()


def test_non_serialisable_positions_fail_before_anything_is_written(tmp_path, monkeypatch):
    from bench import scorer
    from bench.strategies.common import Result

    real = scorer.STRATEGIES["one_day"]

    def bad(preds, prices, costs, start):
        r = real(preds, prices, costs, start)
        return Result(r.ledger, r.equity, [{"asset": "AAA", "x": float("nan")}])

    monkeypatch.setitem(scorer.STRATEGIES, "one_day", bad)
    st = Store(tmp_path)
    for m in ("m1", "m2", "m3"):
        save(st, m, 0.01)
    with pytest.raises(ValueError):
        score_store(st, px(), ASSETS, Settings(), REG)
    assert not (tmp_path / "accounts").exists()
    assert not (tmp_path / "estimators" / "ensemble" / "predictions").exists() or not list((tmp_path / "estimators" / "ensemble" / "predictions").glob("*.json"))
