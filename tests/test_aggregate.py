import json

import pytest

from bench.aggregate import build_all
from bench.broker import settle_estimator
from bench.config import Asset, Settings
from bench.store import Store
from tests.helpers import candles

S = Settings()
ASSETS = [Asset("AAA", "stock", 5), Asset("BBB", "stock", 5)]


def prices():
    return {
        "AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)]),
        "BBB": candles([("2026-01-02", 50, 51, 49, 50), ("2026-01-05", 50, 51, 48, 49)]),
    }


def pred(asof, exp):
    return {"asof": asof, "expected_return": exp, "confidence": None, "path": None}


@pytest.fixture
def out(tmp_path):
    live = Store(tmp_path / "data" / "live")
    live.save_prediction("control_always_long", "2026-01-03", {"predictions": {
        "AAA": pred("2026-01-02", 1.0), "BBB": pred("2026-01-02", 1.0)}})
    live.save_prediction("control_random", "2026-01-03", {"predictions": {
        "AAA": pred("2026-01-02", 1.0), "BBB": pred("2026-01-02", -1.0)}})
    for n in ("control_always_long", "control_random"):
        settle_estimator(live, n, prices(), S)
        live.record_run(n, {"run_date": "2026-01-06", "estimator": n, "status": "ok"})
    live.record_run("analog", {"run_date": "2026-01-06", "estimator": "analog", "status": "failed", "error": "x"})
    target = tmp_path / "site" / "data"
    build_all(tmp_path / "data", target, prices(), S, ASSETS, "2026-01-06", generated_at="2026-01-06T00:41:00Z")
    return target


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_summary_shape_and_numbers(out):
    s = load(out / "summary.json")
    live = s["modes"]["live"]
    assert s["run_date"] == "2026-01-06" and s["stale_assets"] == {}
    assert live["dates"] == ["2026-01-05"]
    al, rnd = live["rows"]["control_always_long"], live["rows"]["control_random"]
    # always long: AAA +0.019, BBB -0.021 -> mean -0.001 ; random only trades AAA -> 0.0095
    assert al["balance"] == pytest.approx(9990.0) and al["day_return"] == pytest.approx(-0.001)
    assert rnd["balance"] == pytest.approx(10095.0) and live["pnl"]["control_random"] == [pytest.approx(0.0095)]
    assert al["hit_rate"] == 0.5 and rnd["hit_rate"] == 1.0 and rnd["hit_rate_down"] == 1.0
    assert al["hit_rate_down"] is None
    assert live["hit"]["control_random"] == [1.0] and live["equity"]["control_random"] == [["2026-01-05", 10095.0]]
    assert al["too_early"] is True and al["n_days"] == 1 and al["trades_per_day"] == 2.0


def test_hold_reference_line(out):
    live = load(out / "summary.json")["modes"]["live"]
    assert live["hold"] == [["2026-01-05", 10000.0]]  # +2% and -2% cancel


def test_failed_and_unrun_estimators(out):
    live = load(out / "summary.json")["modes"]["live"]
    assert live["rows"]["analog"]["status"] == "failed" and live["rows"]["analog"]["n_days"] == 0
    assert live["rows"]["xgb_indicators"]["status"] == "no_run"
    assert live["pnl"]["analog"] == [None]


def test_backtest_mode_is_empty_not_missing(out):
    bt = load(out / "summary.json")["modes"]["backtest"]
    assert bt["dates"] == [] and bt["rows"]["analog"]["n_days"] == 0


def test_estimator_detail_file(out):
    d = load(out / "estimators" / "control_random.json")["modes"]["live"]
    assert len(d["days"]) == 1 and len(d["days"][0]["trades"]) == 2
    assert d["per_asset"]["AAA"]["hit_rate"] == 1.0
    empty = load(out / "estimators" / "analog.json")["modes"]["live"]
    assert empty["days"] == [] and empty["per_asset"] == {}


def test_meta_has_no_internal_keys(out):
    meta = load(out / "summary.json")["estimators"][0]
    assert "target" not in meta and "requirements" not in meta and "label" in meta
