import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from bench.store import Store
from scripts.verify_data import check
from tests.helpers import candles, score

ROOT = Path(__file__).resolve().parent.parent


def setup(tmp_path):
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    df = candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)])
    df.to_csv(prices_dir / "SPY.csv", index=False)
    st = Store(tmp_path / "live")
    st.save_prediction("e", "2026-01-03", {"predictions": {
        "SPY": {"asof": "2026-01-02", "expected_return": 0.01, "confidence": None, "path": None}}})
    score(st, {"SPY": df}, registry={"e": {"kind": "ml"}})
    return st


def acct(st, strategy="one_day"):
    return st.acct_dir("e", strategy)


def test_clean_data_passes(tmp_path):
    setup(tmp_path)
    assert check(tmp_path, ROOT / "assets.yaml") == []


def test_look_ahead_is_caught(tmp_path):
    st = setup(tmp_path)
    f = st.est_dir("e") / "predictions" / "2026-01-03.json"
    payload = json.loads(f.read_text())
    payload["predictions"]["SPY"]["asof"] = "2026-01-03"
    f.write_text(json.dumps(payload))
    assert any("not before" in p for p in check(tmp_path, ROOT / "assets.yaml"))


def test_tampered_equity_is_caught(tmp_path):
    st = setup(tmp_path)
    p = acct(st) / "equity.csv"
    eq = pd.read_csv(p)
    eq.loc[0, "equity"] = 99999.0
    eq.to_csv(p, index=False)
    assert any("compound" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_ledger_price_mismatch_is_caught(tmp_path):
    st = setup(tmp_path)
    p = acct(st) / "ledger.csv"
    led = pd.read_csv(p)
    led.loc[0, "exit"] = 150.0
    led.to_csv(p, index=False)
    assert any("candle" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_script_runs_directly_from_a_file_path(tmp_path):
    setup(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_data.py"), str(tmp_path)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "data checks passed" in r.stdout


def test_nan_in_last_equity_row_is_caught(tmp_path):
    st = setup(tmp_path)
    p = acct(st) / "equity.csv"
    eq = pd.read_csv(p)
    eq.loc[len(eq) - 1, "equity"] = float("nan")
    eq.to_csv(p, index=False)
    assert any("non-finite" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_nan_in_ledger_numeric_column_is_caught(tmp_path):
    st = setup(tmp_path)
    p = acct(st) / "ledger.csv"
    led = pd.read_csv(p)
    led.loc[0, "net_ret"] = float("nan")
    led.to_csv(p, index=False)
    assert any("non-finite" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_duplicate_price_date_is_caught(tmp_path):
    setup(tmp_path)
    f = tmp_path / "prices" / "SPY.csv"
    df = pd.read_csv(f)
    pd.concat([df, df.iloc[[1]]]).to_csv(f, index=False)
    assert any("prices/SPY" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_non_monotonic_price_dates_are_caught(tmp_path):
    setup(tmp_path)
    f = tmp_path / "prices" / "SPY.csv"
    pd.read_csv(f).iloc[::-1].to_csv(f, index=False)
    assert any("prices/SPY" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_all_bad_ledger_rows_are_reported(tmp_path):
    st = setup(tmp_path)
    st.save_prediction("e", "2026-01-06", {"predictions": {
        "SPY": {"asof": "2026-01-05", "expected_return": 0.01, "confidence": None, "path": None}}})
    df = pd.read_csv(tmp_path / "prices" / "SPY.csv")
    df = pd.concat([df, candles([("2026-01-06", 102, 104, 101, 103)])], ignore_index=True)
    df.to_csv(tmp_path / "prices" / "SPY.csv", index=False)
    score(st, {"SPY": df}, registry={"e": {"kind": "ml"}})
    p = acct(st) / "ledger.csv"
    led = pd.read_csv(p)
    led["exit"] = 150.0
    led.to_csv(p, index=False)
    assert sum("candle" in problem for problem in check(tmp_path, ROOT / "assets.yaml")) == len(led)


def test_crypto_prediction_must_be_asof_the_day_before_the_run(tmp_path):
    st = setup(tmp_path)
    st.save_prediction("e", "2026-01-06", {"predictions": {
        "BTC-USD": {"asof": "2026-01-03", "expected_return": 0.01, "confidence": None, "path": None}}})
    assert any("crypto" in p and "asof" in p for p in check(tmp_path, ROOT / "assets.yaml"))


def test_day_returns_must_follow_from_the_ledger(tmp_path):
    st = setup(tmp_path)
    p = acct(st) / "equity.csv"
    eq = pd.read_csv(p)
    eq.loc[0, "day_return"] = 0.5
    eq["equity"] = 10000.0 * (1 + eq["day_return"]).cumprod()  # compounds, but no longer matches the ledger
    eq.to_csv(p, index=False)
    problems = check(tmp_path, ROOT / "assets.yaml")
    assert any("do not follow from the ledger" in x for x in problems)
    assert not any("compound" in x for x in problems)


def test_forced_close_without_a_prediction_is_not_a_problem(tmp_path):
    """A hold position sold because the model stopped predicting has no expected return."""
    from bench.config import Asset
    from bench.store import Store
    from tests.helpers import candles, score

    px = {"AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102), ("2026-01-07", 103, 104, 101, 103)])}
    (tmp_path / "prices").mkdir()
    px["AAA"].to_csv(tmp_path / "prices" / "AAA.csv", index=False)
    assets = tmp_path / "assets.yaml"
    assets.write_text("assets:\n  - {symbol: AAA, group: stock, max_gap_days: 5, cost_round_trip: 0.001}\n", encoding="utf-8")
    st = Store(tmp_path / "live")
    st.save_prediction("control_always_long", "2026-01-06", {
        "schema_version": 2, "estimator": "control_always_long", "run_date": "2026-01-06", "created_at": None,
        "predictions": {"AAA": {"asof": "2026-01-05", "expected_return": 1.0, "confidence": None, "path": None}},
    })
    score(st, px, [Asset("AAA", "stock", 5, 0.001, 0.0)])
    led = st.load_account("control_always_long", "hold")[1]
    assert led["action"].tolist() == ["open", "close"] and led["expected_return"].isna().tolist() == [False, True]
    assert check(tmp_path, assets) == []
