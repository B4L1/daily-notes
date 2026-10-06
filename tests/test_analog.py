import pandas as pd
import pytest

from estimators.analog.predict import Analog


def periodic(n=252):
    """Returns cycle +2%, -1%, +0.5%, -2% so every 3-candle window identifies its phase."""
    cycle = [0.02, -0.01, 0.005, -0.02]
    close, prev, rows = [], 100.0, []
    for i in range(n):
        r = cycle[i % 4]
        c = prev * (1 + r)
        rows.append({
            "date": f"d{i:04d}", "open": prev, "close": c,
            "high": max(prev, c) * 1.001, "low": min(prev, c) * 0.999, "volume": 1,
        })
        prev = c
    return pd.DataFrame(rows)


def test_predicts_the_next_phase_of_a_repeating_pattern():
    out = Analog().predict({"AAA": periodic()}, ["AAA"])
    # 252 candles: the last candle is phase 3, so the next return is the cycle's first, +2%.
    assert out["AAA"].expected_return == pytest.approx(0.02, abs=1e-6)
    assert out["AAA"].confidence == 1.0


def test_too_little_history_is_omitted():
    assert Analog().predict({"AAA": periodic(100)}, ["AAA"]) == {}
