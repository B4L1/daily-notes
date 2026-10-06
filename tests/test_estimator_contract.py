import importlib
import inspect
import math

import pytest

from estimators import registry
from estimators.base import Estimator, Prediction
from tests.helpers import random_walk


def _external_missing(e):
    """True only when the missing module is a third-party dependency (xgboost, torch, ...)."""
    return e.name is not None and not e.name.startswith(("estimators", "bench", "tests"))


def skip_if_missing_dependency(fn):
    """Call fn(); return None for a missing external package, re-raise any other ImportError."""
    try:
        return fn()
    except ImportError as e:
        if _external_missing(e):
            return None
        raise


def available(name):
    return skip_if_missing_dependency(lambda: registry.build(name))


NAMES = registry.names()
ASKED = ["AAA", "BBB", "SHORT"]


def make_history():
    return {
        "AAA": random_walk(420, seed=1),
        "BBB": random_walk(420, seed=2),
        "SHORT": random_walk(3, seed=3),  # below every estimator's minimum history
        "CCC": random_walk(420, seed=4),  # present in history but never asked about
    }


def check_contract(est, history, controls_may_keep_short=False):
    before = {a: df.copy() for a, df in history.items()}
    out = est.predict(history, ASKED)
    assert set(out) <= set(ASKED), "returned an asset it was not asked about"
    for a, p in out.items():
        assert math.isfinite(p.expected_return), (est.name, a)
    assert "SHORT" not in out or controls_may_keep_short, "too little history must be omitted"
    again = est.predict(history, ASKED)
    assert again == out, "predictions must be deterministic"
    for a in history:
        assert history[a].equals(before[a]), "estimator mutated its input"


@pytest.fixture(scope="module")
def history():
    return make_history()


@pytest.mark.parametrize("name", NAMES)
def test_contract(name, history):
    est = available(name)
    if est is None:
        pytest.skip(f"{name}: dependencies not installed here")
    check_contract(est, history, controls_may_keep_short=name.startswith("control_"))


class _Base(Estimator):
    name = "throwaway"


class _UnaskedAsset(_Base):
    def predict(self, history, assets):
        return {"CCC": Prediction(0.0)}


class _Mutates(_Base):
    def predict(self, history, assets):
        history["AAA"].loc[0, "close"] += 1.0
        return {"AAA": Prediction(0.0)}


class _Nondeterministic(_Base):
    def __init__(self):
        self.n = 0

    def predict(self, history, assets):
        self.n += 1
        return {"AAA": Prediction(float(self.n))}


class _Good(_Base):
    def predict(self, history, assets):
        return {"AAA": Prediction(0.0)}


def test_check_contract_accepts_a_good_estimator():
    check_contract(_Good(), make_history())


@pytest.mark.parametrize("bad", [_UnaskedAsset, _Mutates, _Nondeterministic])
def test_check_contract_rejects_violations(bad):
    with pytest.raises(AssertionError):
        check_contract(bad(), make_history())


def test_broken_first_party_import_is_not_skipped(tmp_path, monkeypatch):
    (tmp_path / "broken_first_party_zzz.py").write_text("import estimators.does_not_exist_zzz\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ImportError):
        skip_if_missing_dependency(lambda: importlib.import_module("broken_first_party_zzz"))


def test_missing_external_package_is_skipped(tmp_path, monkeypatch):
    (tmp_path / "needs_external_zzz.py").write_text("import not_a_real_package_zzz\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert skip_if_missing_dependency(lambda: importlib.import_module("needs_external_zzz")) is None


@pytest.mark.parametrize("name", NAMES)
def test_no_network_in_estimator_source(name):
    module = registry.REGISTRY[name]["target"].split(":")[0]
    mod = skip_if_missing_dependency(lambda: importlib.import_module(module))
    if mod is None:
        pytest.skip(f"{name}: dependencies not installed here")
    src = inspect.getsource(mod)
    for banned in ("yfinance", "requests", "urllib.request", "socket"):
        assert banned not in src, f"{name} must not access the network itself ({banned})"
