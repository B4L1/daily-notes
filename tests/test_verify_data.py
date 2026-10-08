import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from bench.config import Settings
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


@pytest.mark.xfail(reason="Task 9 moves the checker to accounts", strict=True)
def test_tampered_equity_is_caught(tmp_path):
    st = setup(tmp_path)
    p = st.est_dir("e") / "equity.csv"
    eq = pd.read_csv(p)
    eq.loc[0, "equity"] = 99999.0
    eq.to_csv(p, index=False)
    assert any("compound" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


@pytest.mark.xfail(reason="Task 9 moves the checker to accounts", strict=True)
def test_ledger_price_mismatch_is_caught(tmp_path):
    st = setup(tmp_path)
    p = st.est_dir("e") / "ledger.csv"
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


@pytest.mark.xfail(reason="Task 9 moves the checker to accounts", strict=True)
def test_nan_in_last_equity_row_is_caught(tmp_path):
    st = setup(tmp_path)
    p = st.est_dir("e") / "equity.csv"
    eq = pd.read_csv(p)
    eq.loc[len(eq) - 1, "equity"] = float("nan")
    eq.to_csv(p, index=False)
    assert any("non-finite" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


@pytest.mark.xfail(reason="Task 9 moves the checker to accounts", strict=True)
def test_nan_in_ledger_numeric_column_is_caught(tmp_path):
    st = setup(tmp_path)
    p = st.est_dir("e") / "ledger.csv"
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


@pytest.mark.xfail(reason="Task 9 moves the checker to accounts", strict=True)
def test_all_bad_ledger_rows_are_reported(tmp_path):
    st = setup(tmp_path)
    st.save_prediction("e", "2026-01-06", {"predictions": {
        "SPY": {"asof": "2026-01-05", "expected_return": 0.01, "confidence": None, "path": None}}})
    p = st.est_dir("e") / "ledger.csv"
    led = pd.read_csv(p)
    led["exit"] = 150.0
    led.to_csv(p, index=False)
    assert sum("candle" in problem for problem in check(tmp_path, ROOT / "assets.yaml")) == len(led)
