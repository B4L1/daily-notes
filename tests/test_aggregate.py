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


def _seed(tmp_path, mode, exps, px):
    st = Store(tmp_path / "data" / mode)
    for n in ("control_always_long", "control_random"):
        st.save_prediction(n, "2026-01-03", {"predictions": {
            a: pred("2026-01-02", e) for a, e in exps.items()}})
        settle_estimator(st, n, px, S)
    return st


def _build(tmp_path, px, assets=ASSETS, run_date="2026-01-06"):
    target = tmp_path / "site" / "data"
    build_all(tmp_path / "data", target, px, S, assets, run_date, generated_at="2026-01-06T00:41:00Z")
    return load(target / "summary.json")


def test_modes_do_not_leak(tmp_path):
    _seed(tmp_path, "live", {"AAA": 1.0, "BBB": 1.0}, prices())
    px2 = {
        "AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 110)]),
        "BBB": candles([("2026-01-02", 50, 51, 49, 50), ("2026-01-05", 50, 51, 48, 50)]),
    }
    _seed(tmp_path, "backtest", {"AAA": 1.0, "BBB": -1.0}, px2)
    s = _build(tmp_path, prices())
    live, bt = s["modes"]["live"], s["modes"]["backtest"]
    assert live["rows"]["control_always_long"]["balance"] == pytest.approx(9990.0)
    assert bt["rows"]["control_always_long"]["balance"] != pytest.approx(9990.0)
    for n in ("control_always_long", "control_random"):
        assert live["equity"][n] != bt["equity"][n]
        assert live["rows"][n]["balance"] != bt["rows"][n]["balance"]
    assert live["rows"]["control_always_long"]["hit_rate"] == 0.5
    # backtest: AAA hit (+10%), BBB flat (hit None, excluded from hit rate, row still builds)
    assert bt["rows"]["control_always_long"]["hit_rate"] == 1.0
    assert bt["hit"]["control_always_long"] == [1.0]


def test_stale_assets_reported(tmp_path):
    px = prices()
    s = _build(tmp_path, px, ASSETS + [Asset("CCC", "stock", 5)], run_date="2026-02-01")
    assert s["stale_assets"]["CCC"] is None
    assert s["stale_assets"]["AAA"] == 26  # newest candle 2026-01-05, cutoff 2026-01-31


def test_sanity_flag_true_on_huge_day(tmp_path):
    px = {
        "AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 130, 99, 125)]),
        "BBB": prices()["BBB"],
    }
    _seed(tmp_path, "live", {"AAA": 1.0}, px)
    row = _build(tmp_path, px)["modes"]["live"]["rows"]["control_always_long"]
    assert row["sanity"] is True
    assert _build(tmp_path, px)["modes"]["live"]["rows"]["analog"]["sanity"] is False


def _walk_store(tmp_path, n_days, mode="live"):
    """control_random trades +1 on AAA every day on a rising series; always_long same + a losing BBB."""
    from datetime import date, timedelta
    d0 = date(2026, 1, 1)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range(n_days + 2)]
    rows_a = [(d, 100 + i, 101 + i, 99 + i, 100 + i) for i, d in enumerate(days)]
    rows_b = [(d, 50, 51, 49, 50 - (i % 2)) for i, d in enumerate(days)]
    px = {"AAA": candles(rows_a), "BBB": candles(rows_b)}
    st = Store(tmp_path / "data" / mode)
    for i in range(n_days):
        asof, settle = days[i], days[i + 1]
        st.save_prediction("control_random", days[i + 1], {"predictions": {"AAA": pred(asof, 1.0)}})
        st.save_prediction("control_always_long", days[i + 1], {"predictions": {
            "AAA": pred(asof, 1.0), "BBB": pred(asof, 1.0)}})
    for n in ("control_random", "control_always_long"):
        settle_estimator(st, n, px, S)
    return px


def test_spark_edge_and_too_early_with_many_days(tmp_path):
    px = _walk_store(tmp_path, 65)
    live = _build(tmp_path, px, run_date="2026-03-20")["modes"]["live"]
    al, rnd = live["rows"]["control_always_long"], live["rows"]["control_random"]
    assert al["n_days"] >= S.min_live_days and al["too_early"] is False
    assert len(al["spark"]) == 30 and len(rnd["spark"]) == 30
    assert al["spark"][-1] == al["balance"]
    # always_long adds a coin-flip BBB leg, so it differs from control_random: edge is the mean daily diff
    diffs = [a - r for a, r in zip(live["pnl"]["control_always_long"], live["pnl"]["control_random"])]
    assert al["edge"] == pytest.approx(sum(diffs) / len(diffs))
    assert 0.0 < al["p_value"] <= 1.0
    assert rnd["edge"] == 0.0 and rnd["p_value"] == 1.0


def test_zero_close_does_not_break_hold(tmp_path):
    px = prices()
    px["BBB"] = candles([("2026-01-02", 50, 51, 49, 0), ("2026-01-05", 50, 51, 48, 49)])
    _seed(tmp_path, "live", {"AAA": 1.0}, prices())
    s = _build(tmp_path, px)
    assert s["modes"]["live"]["hold"] == [["2026-01-05", 10200.0]]  # only AAA's +2% step counts
    json.dumps(s, allow_nan=False)


def test_summary_meta_exposes_backfill_stride(out):
    s = load(out / "summary.json")
    assert {e["name"]: e["backfill_stride"] for e in s["estimators"]}["kronos"] == 1
    assert all(isinstance(e["backfill_stride"], int) and e["backfill_stride"] >= 1 for e in s["estimators"])
