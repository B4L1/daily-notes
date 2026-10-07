import numpy as np
import pytest

from estimators.adapter import ClosesForecaster
from tests.helpers import random_walk


class _Flat(ClosesForecaster):
    name = "flat"
    window = 50

    def _forecast(self, df, horizon):
        self.seen = len(df)
        return [float(df["close"].iloc[-1]) * 1.01] * horizon


class _WrongShape(_Flat):
    def _forecast(self, df, horizon):
        return [1.0]


def test_adapter_windows_and_builds_prediction_with_path():
    est = _Flat()
    out = est.predict({"A": random_walk(320), "S": random_walk(10)}, ["A", "S"])
    assert set(out) == {"A"}
    assert est.seen == 50
    assert out["A"].expected_return == pytest.approx(0.01)
    assert len(out["A"].path) == 5


def test_adapter_rejects_wrong_forecast_length():
    with pytest.raises(ValueError):
        _WrongShape().predict({"A": random_walk(320)}, ["A"])
