import importlib
import inspect
import math

import pytest

from estimators import registry
from tests.helpers import random_walk


def available(name):
    try:
        return registry.build(name)
    except ImportError:
        return None


NAMES = registry.names()


@pytest.fixture(scope="module")
def history():
    return {
        "AAA": random_walk(420, seed=1),
        "BBB": random_walk(420, seed=2),
        "SHORT": random_walk(3, seed=3),  # below every estimator's minimum history
    }


@pytest.mark.parametrize("name", NAMES)
def test_contract(name, history):
    est = available(name)
    if est is None:
        pytest.skip(f"{name}: dependencies not installed here")
    before = {a: df.copy() for a, df in history.items()}
    out = est.predict(history, ["AAA", "BBB", "SHORT"])
    assert set(out) <= {"AAA", "BBB", "SHORT"}
    for a, p in out.items():
        assert math.isfinite(p.expected_return), (name, a)
    assert "SHORT" not in out or name.startswith("control_"), "too little history must be omitted"
    again = est.predict(history, ["AAA", "BBB", "SHORT"])
    assert again == out, "predictions must be deterministic"
    for a in history:
        assert history[a].equals(before[a]), "estimator mutated its input"


@pytest.mark.parametrize("name", NAMES)
def test_no_network_in_estimator_source(name):
    module = registry.REGISTRY[name]["target"].split(":")[0]
    try:
        src = inspect.getsource(importlib.import_module(module))
    except ImportError:
        pytest.skip(f"{name}: dependencies not installed here")
    for banned in ("yfinance", "requests", "urllib.request", "socket"):
        assert banned not in src, f"{name} must not access the network itself ({banned})"
