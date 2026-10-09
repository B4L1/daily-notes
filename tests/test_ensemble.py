import pytest

from bench.config import Asset
from bench.costs import Costs
from bench.ensemble import NAME, derive

C = Costs([Asset("AAA", "stock", 5, 0.001, 0.0)])


def model(exp, asof="2026-01-05", run_date="2026-01-06"):
    return {run_date: {"predictions": {"AAA": {"asof": asof, "expected_return": exp, "path": None}}}}


def vote(*exps):
    out = derive({f"m{i}": model(e) for i, e in enumerate(exps)}, C)
    return out["2026-01-06"]["predictions"]["AAA"]["expected_return"]


def test_majority_up_and_down():
    assert vote(0.01, 0.02, -0.01) == 1.0
    assert vote(-0.01, -0.02, 0.01) == -1.0


def test_tie_and_weak_calls_are_no_trade():
    assert vote(0.01, -0.01) == 0.0
    assert vote(0.01, 0.0005, 0.0005) == 0.0  # only one of three beats the cost


def test_exactly_half_is_not_a_majority():
    assert vote(0.01, 0.01, -0.01, 0.0) == 0.0


def test_payload_shape():
    p = derive({"m0": model(0.01)}, C)["2026-01-06"]
    assert p["estimator"] == NAME and p["run_date"] == "2026-01-06" and p["schema_version"] == 2
    assert p["predictions"]["AAA"] == {"asof": "2026-01-05", "expected_return": 1.0, "confidence": 1.0, "path": None}


def conf(*exps):
    out = derive({f"m{i}": model(e) for i, e in enumerate(exps)}, C)
    return out["2026-01-06"]["predictions"]["AAA"]["confidence"]


def test_confidence_is_the_vote_share_of_the_winning_side():
    assert conf(0.01, 0.02, -0.01) == pytest.approx(2 / 3)
    assert conf(-0.01, -0.02, -0.03, 0.01) == pytest.approx(3 / 4)
    assert conf(0.01, -0.01) is None  # no majority


def test_votes_only_count_for_the_newest_asof():
    saved = {"fresh1": model(0.01, asof="2026-01-05"), "fresh2": model(0.01, asof="2026-01-05"),
             "stale1": model(-0.5, asof="2026-01-02"), "stale2": model(-0.5, asof="2026-01-02"),
             "stale3": model(-0.5, asof="2026-01-02")}
    p = derive(saved, C)["2026-01-06"]["predictions"]["AAA"]
    assert p["asof"] == "2026-01-05" and p["expected_return"] == 1.0


def test_no_voters_no_files():
    assert derive({}, C) == {}
    assert derive({"m0": {}}, C) == {}


def test_asset_missing_from_a_model_is_not_a_vote():
    saved = {"m0": model(0.01), "m1": {"2026-01-06": {"predictions": {}}}}
    assert derive(saved, C)["2026-01-06"]["predictions"]["AAA"]["expected_return"] == 1.0
