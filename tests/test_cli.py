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
    assert not (base / "equity.csv").exists() and not (env / "data" / "backtest" / "accounts").exists()  # scoring is a separate step
    assert not (env / "data" / "live" / "estimators").exists()


def test_backfill_stride_comes_from_the_registry(env, monkeypatch):
    from estimators import registry

    now = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
    base = env / "data" / "backtest" / "estimators" / "control_always_long" / "predictions"
    cli.main(["backfill", "--estimator", "control_always_long", "--days", "20", "--end", "2026-03-01"], now=now)
    every_day = len(list(base.glob("*.json")))
    for f in base.glob("*.json"):
        f.unlink()
    monkeypatch.setitem(registry.REGISTRY["control_always_long"], "backfill_stride", 3)
    cli.main(["backfill", "--estimator", "control_always_long", "--days", "20", "--end", "2026-03-01"], now=now)
    assert len(list(base.glob("*.json"))) < every_day
    assert registry.backfill_stride("kronos") == 1 and registry.backfill_stride("timesfm") == 1


def test_freshness_warnings_flag_short_crypto_fetch():
    from bench.config import Asset
    from tests.helpers import candles

    prices = {
        "BTC-USD": candles([("2026-10-06", 1, 1, 1, 1)]),  # missing 10-07 for run date 10-08
        "SPY": candles([("2026-10-07", 1, 1, 1, 1)]),
    }
    assets = [Asset("BTC-USD", "crypto", 0), Asset("SPY", "stock", 5)]
    lines = cli.freshness_warnings(prices, assets, "2026-10-08")
    assert lines[0] == "WARNING: BTC-USD newest candle 2026-10-06 is older than expected 2026-10-07"
    assert lines[1].startswith("::warning::BTC-USD") and len(lines) == 2
    fresh = {"BTC-USD": prices["BTC-USD"], "SPY": candles([("2026-10-06", 1, 1, 1, 1)])}
    assert cli.freshness_warnings(fresh, assets, "2026-10-07") == []


def test_fetch_prints_the_freshness_warning_and_does_not_fail(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "update_prices", lambda d, a, st, through=None: {x.symbol: "ok" for x in a})
    rc = cli.main(["fetch"], now=datetime(2026, 10, 8, 6, 22, tzinfo=timezone.utc))
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING: SPY newest candle 2026-03-01 is older than expected 2026-10-02" in out
    assert "::warning::BTC-USD newest candle none" in out


def test_score_command_writes_accounts(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "prices").mkdir(parents=True)
    random_walk(40, start="2026-01-01").to_csv(data / "prices" / "AAA.csv", index=False)
    assets = tmp_path / "assets.yaml"
    assets.write_text("assets:\n  - {symbol: AAA, group: stock, max_gap_days: 5, cost_round_trip: 0.001}\n", encoding="utf-8")
    monkeypatch.setenv("BENCH_DATA", str(data))
    monkeypatch.setenv("BENCH_ASSETS", str(assets))
    pred = data / "backtest" / "estimators" / "control_always_long" / "predictions"
    pred.mkdir(parents=True)
    pred.joinpath("2026-01-11.json").write_text(json.dumps({
        "schema_version": 1, "estimator": "control_always_long", "run_date": "2026-01-11", "created_at": None,
        "predictions": {"AAA": {"asof": "2026-01-10", "expected_return": 1.0, "confidence": None, "path": None}},
    }), encoding="utf-8")
    now = datetime(2026, 2, 9, 1, 0, tzinfo=timezone.utc)
    assert cli.main(["score", "--mode", "backtest"], now=now) == 0
    assert (data / "backtest" / "accounts" / "control_always_long" / "hold" / "equity.csv").exists()
    # live mode with nothing in it is fine
    assert cli.main(["score", "--mode", "all"], now=now) == 0
