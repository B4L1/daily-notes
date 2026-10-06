import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bench import cli
from tests.helpers import random_walk

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("BENCH_ASSETS", str(ROOT / "assets.yaml"))
    prices = tmp_path / "data" / "prices"
    prices.mkdir(parents=True)
    random_walk(60, "2026-01-01").to_csv(prices / "SPY.csv", index=False)
    return tmp_path


def test_list_prints_registry_names(capsys):
    assert cli.main(["list"]) == 0
    names = json.loads(capsys.readouterr().out)
    assert "control_random" in names and "xgb_indicators" in names


def test_requirements_command(capsys):
    cli.main(["requirements", "--estimator", "xgb_indicators"])
    assert capsys.readouterr().out.strip() == "estimators/xgb_indicators/requirements.txt"
    cli.main(["requirements", "--estimator", "control_random"])
    assert capsys.readouterr().out.strip() == ""


def test_run_writes_a_prediction(env, capsys):
    now = datetime(2026, 3, 2, 0, 40, tzinfo=timezone.utc)  # prices run to 2026-03-01
    assert cli.main(["run", "--estimator", "control_always_long", "--run-date", "2026-03-02"], now=now) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["status"] == "ok" and rec["n_predictions"] == 1
    assert (env / "data" / "live" / "estimators" / "control_always_long" / "predictions" / "2026-03-02.json").exists()


def test_run_returns_nonzero_when_the_estimator_failed(env, monkeypatch):
    from estimators import registry

    class Boom:
        name = "boom_for_test"
        backfill_stride = 1

        def predict(self, history, assets):
            raise RuntimeError("x")

    monkeypatch.setattr(registry, "build", lambda name: Boom())
    now = datetime(2026, 3, 2, 0, 40, tzinfo=timezone.utc)
    assert cli.main(["run", "--estimator", "control_always_long", "--run-date", "2026-03-02"], now=now) == 1


def test_backfill_replays_days_into_the_backtest_store(env, capsys):
    now = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
    code = cli.main(["backfill", "--estimator", "control_always_long", "--days", "20", "--end", "2026-03-01"], now=now)
    assert code == 0
    base = env / "data" / "backtest" / "estimators" / "control_always_long"
    assert len(list((base / "predictions").glob("*.json"))) >= 1
    assert (base / "equity.csv").exists()
    assert not (env / "data" / "live" / "estimators").exists()
