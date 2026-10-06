from estimators.candle_rules.predict import CandleRules, _signal
from tests.helpers import candles


def arrays(rows):
    df = candles(rows)
    return tuple(df[c].to_numpy(float) for c in ("open", "high", "low", "close"))


def test_hammer_after_downtrend_is_bullish():
    o, h, l, c = arrays([
        ("d1", 10.2, 10.3, 9.9, 10.0), ("d2", 10.0, 10.0, 9.7, 9.8), ("d3", 9.8, 9.8, 9.5, 9.6),
        ("d4", 9.6, 9.6, 9.3, 9.4), ("d5", 9.4, 9.45, 8.8, 9.42),
    ])
    assert _signal(o, h, l, c) == 1


def test_shooting_star_after_uptrend_is_bearish():
    o, h, l, c = arrays([
        ("d1", 9.8, 10.0, 9.7, 10.0), ("d2", 10.0, 10.3, 9.9, 10.2), ("d3", 10.2, 10.5, 10.1, 10.4),
        ("d4", 10.4, 10.7, 10.3, 10.6), ("d5", 10.6, 11.2, 10.58, 10.62),
    ])
    assert _signal(o, h, l, c) == -1


def test_bullish_engulfing():
    o, h, l, c = arrays([
        ("d1", 10, 10.1, 9.9, 10.0), ("d2", 10, 10.1, 9.8, 9.9), ("d3", 9.9, 10.0, 9.7, 9.8),
        ("d4", 10.0, 10.0, 8.9, 9.0), ("d5", 8.9, 10.3, 8.8, 10.2),
    ])
    assert _signal(o, h, l, c) == 1


def test_bearish_engulfing():
    o, h, l, c = arrays([
        ("d1", 9, 9.1, 8.9, 9.0), ("d2", 9, 9.4, 8.9, 9.3), ("d3", 9.3, 9.6, 9.2, 9.5),
        ("d4", 9.0, 10.1, 8.9, 10.0), ("d5", 10.2, 10.3, 8.7, 8.8),
    ])
    assert _signal(o, h, l, c) == -1


def test_nothing_special_is_zero():
    o, h, l, c = arrays([("d%d" % i, 10, 10.2, 9.8, 10.1) for i in range(5)])
    assert _signal(o, h, l, c) == 0


def test_estimator_maps_signal_to_expected_return():
    df = candles([
        ("d1", 10, 10.1, 9.9, 10.0), ("d2", 10, 10.1, 9.8, 9.9), ("d3", 9.9, 10.0, 9.7, 9.8),
        ("d4", 10.0, 10.0, 8.9, 9.0), ("d5", 8.9, 10.3, 8.8, 10.2),
    ])
    out = CandleRules().predict({"AAA": df, "SHORT": df.iloc[:3]}, ["AAA", "SHORT"])
    assert out["AAA"].expected_return == 0.002 and "SHORT" not in out
