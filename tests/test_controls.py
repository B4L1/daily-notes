import pytest

from estimators.controls.predict import AlwaysLong, Persistence, RandomCoin
from tests.helpers import candles, random_walk


def hist():
    return {"AAA": random_walk(10), "EMPTY": candles([])}


def test_always_long_skips_assets_without_candles():
    out = AlwaysLong().predict(hist(), ["AAA", "EMPTY"])
    assert list(out) == ["AAA"] and out["AAA"].expected_return == 1.0


def test_random_is_deterministic_and_two_valued():
    a = RandomCoin().predict(hist(), ["AAA"])
    b = RandomCoin().predict(hist(), ["AAA"])
    assert a == b and a["AAA"].expected_return in (1.0, -1.0)


def test_random_is_not_always_the_same_across_days():
    h = {"AAA": random_walk(200)}
    values = set()
    for n in range(20, 200):
        values.add(RandomCoin().predict({"AAA": h["AAA"].iloc[:n]}, ["AAA"])["AAA"].expected_return)
    assert values == {1.0, -1.0}


def test_persistence_repeats_the_last_return():
    df = candles([("2026-01-02", 1, 1, 1, 100), ("2026-01-05", 1, 1, 1, 102)])
    out = Persistence().predict({"AAA": df}, ["AAA"])
    assert out["AAA"].expected_return == pytest.approx(0.02)
    assert Persistence().predict({"AAA": df.iloc[:1]}, ["AAA"]) == {}
