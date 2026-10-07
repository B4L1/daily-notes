import hashlib
import math

import pandas as pd
import pytest

from bench.config import Settings
from bench.runner import run_estimator_day
from bench.store import Store
from estimators.adapter import ClosesForecaster
from estimators.timesfm import fetch_assets
from tests.helpers import random_walk


def test_weights_ok_rejects_missing_truncated_and_altered_files(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESFM_WEIGHTS", str(tmp_path))
    assert not fetch_assets.weights_ok()
    good = b"not the real weights"
    monkeypatch.setattr(fetch_assets, "WEIGHTS_SHA256", hashlib.sha256(good).hexdigest())
    f = tmp_path / "model.safetensors"
    f.write_bytes(good)
    assert fetch_assets.weights_ok()
    f.write_bytes(good[:-3])
    assert not fetch_assets.weights_ok()
    f.write_bytes(good[:-1] + b"X")
    assert not fetch_assets.weights_ok()


def test_estimator_refuses_to_load_without_verified_weights(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setenv("TIMESFM_WEIGHTS", str(tmp_path))
    (tmp_path / "model.safetensors").write_bytes(b"truncated")
    from estimators.timesfm.predict import TimesFM

    with pytest.raises(ImportError, match="setup --estimator timesfm"):
        TimesFM()


def test_nan_forecast_is_a_failed_run_not_a_zero(tmp_path):
    class Nan(ClosesForecaster):
        name = "nanfc"

        def _forecast(self, df, horizon):
            return [math.nan] * horizon

    prices = {"A": random_walk(320)}
    st = Store(tmp_path)
    run_date = (pd.to_datetime(prices["A"]["date"].iloc[-1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    rec = run_estimator_day(st, Nan(), prices, run_date, Settings())
    assert rec["status"] == "failed" and "non-finite" in rec["error"]
    assert st.load_predictions("nanfc") == {}
