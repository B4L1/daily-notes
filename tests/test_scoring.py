import pytest

from bench import scoring


def test_total_return_and_empty():
    assert scoring.total_return([10100, 10500], 10000) == pytest.approx(0.05)
    assert scoring.total_return([], 10000) == 0.0


def test_max_drawdown():
    assert scoring.max_drawdown([100, 120, 90, 110]) == pytest.approx(-0.25)
    assert scoring.max_drawdown([100, 101, 102]) == 0.0
    assert scoring.max_drawdown([]) == 0.0


def test_worst_day():
    assert scoring.worst_day([0.01, -0.03, 0.02]) == -0.03
    assert scoring.worst_day([]) == 0.0


def test_hit_rate_skips_missing():
    assert scoring.hit_rate([1, 0, 1, float("nan"), None]) == pytest.approx(2 / 3)
    assert scoring.hit_rate([]) is None


def test_pvalue_clear_edge_is_small():
    assert scoring.sign_flip_pvalue([0.01] * 30) < 0.01


def test_pvalue_no_edge_is_large():
    diffs = [0.01, -0.01] * 15
    assert scoring.sign_flip_pvalue(diffs) > 0.3


def test_pvalue_needs_data():
    assert scoring.sign_flip_pvalue([0.01]) == 1.0
    assert scoring.sign_flip_pvalue([0.0, 0.0, 0.0]) == 1.0


def test_pvalue_is_deterministic():
    d = [0.01, -0.02, 0.03, 0.0, 0.01]
    assert scoring.sign_flip_pvalue(d) == scoring.sign_flip_pvalue(d)


def test_edge_aligns_dates():
    est = {"d1": 0.02, "d2": 0.01, "d3": 0.5}
    ctl = {"d1": 0.01, "d2": 0.00}
    out = scoring.edge_vs_control(est, ctl)
    assert out["n"] == 2 and out["edge"] == pytest.approx(0.01)


def test_sanity_flag():
    assert scoring.sanity_flag([0.0, 0.11], 0.10, 0.50) is True
    assert scoring.sanity_flag([0.01] * 7, 0.10, 0.50) is False
    assert scoring.sanity_flag([0.07] * 7, 0.10, 0.50) is True  # 1.07**7 - 1 = 0.605
    assert scoring.sanity_flag([], 0.10, 0.50) is False
