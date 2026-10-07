# Prediction Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fully automated daily bench that runs many price predictors on ~21 assets, paper-trades each one in its own continuous $10,000 account under identical rules, and publishes a terminal-style dashboard plus a daily phone notification.

**Architecture:** One public GitHub repo. A scheduled GitHub Actions workflow fetches prices, runs one isolated matrix job per estimator (settle yesterday, predict tomorrow), then an aggregate job commits the data files, builds static JSON for the dashboard, deploys GitHub Pages and sends an ntfy message. The repo's `data/` folder is the database. The same `run_estimator_day` function drives both the live run and the one-year backfill, so the two can never disagree.

**Tech Stack:** Python 3.11, pandas, numpy, PyYAML, yfinance, XGBoost, pytest; vanilla HTML/CSS/ES-module JS (no build step, no runtime dependencies) tested with `node --test`; GitHub Actions and Pages; ntfy.sh.

**Spec:** `docs/superpowers/specs/2026-10-01-prediction-bench-design.md` (read it first; this plan implements it section by section).

## Global Constraints

- Python 3.11 or newer. Runtime deps: `pandas>=2.2`, `numpy>=1.26`, `PyYAML>=6`, `yfinance>=0.2.40`. Per-estimator deps live in that estimator's own `requirements.txt`.
- Paper trading only. No real money, no broker connection, no order placement.
- Each account starts at $10,000, is continuous (full balance carries to the next day, no reset or top-up), and is split equally each day across the assets that have a session that day.
- Long-only. Trade when `expected_return > trade_threshold` (default equals `cost_round_trip`). Enter at the target session's open, exit at its close. Cost 0.1% round trip (`cost_round_trip: 0.001`), charged on every trade.
- Nothing is invented: a failed estimator stays in cash and is recorded `failed`; a failed price fetch leaves the asset stale; no value is ever filled in from a previous day.
- The harness gives an estimator only candles dated `<= run_date - 1 day`. Predictions are written before their outcome exists.
- Daily schedule is cron `30 0 * * *` (00:30 UTC). A live run that starts more than 12 hours after 00:00 UTC (originally 6; widened after the first scheduled run started 5h43m late) of its run date records `skipped_late` and makes no prediction.
- Backtest and live are separate stores (`data/backtest`, `data/live`), shown behind a Live / Backtest switch. Pretrained-model backtests are labelled "may be optimistic".
- The repo is public. The ntfy topic lives only in the GitHub secret `NTFY_TOPIC`; never in code, logs or the repo. Notifications use ntfy priority 2 (low).
- Every data file set carries `schema_version` 1 (the `SCHEMA` marker file in each data root).
- Dashboard: terminal style (dark, monospace, dense). Two heatmap views (daily return and direction hit rate), green/red by default, brighter for larger magnitude; colour is never the only signal (▲/▼ markers in tooltips and tables); a colour-blind palette (blue/orange) switch; minimal motion that respects `prefers-reduced-motion`. A "check this" badge when an account gains more than +10% in a day or +50% in a week. "Too early to tell" until 60 live trading days exist. Footer: "Paper trading experiment on public price data. Not investment advice."
- Rulebook: Foundry's *The Book of Coding Secrets* at `C:\Claude Projects\Foundry\02-book\`. Applied chapters are listed in the spec section 13 and each task names the chapters to read first.

## Review Focus

The spec is silent on these inputs, and each will bite someone using the bench. The test that pins each one is in the named task.

1. **Bad price data** (empty frame, NaN rows, duplicate dates, a fetch that raises) must never corrupt or wipe the cached candles. Task 2.
2. **Days with no session for an asset** (weekend for stocks, holiday, a crypto-only day) must neither crash nor dilute an account wrongly; the equal split counts only assets with a candle that day. Tasks 3 and 5.
3. **Estimator output that is NaN, infinite, or names assets nobody asked for** must be rejected or ignored and recorded, never saved as a prediction. Task 5.
4. **Re-running a day** (manual dispatch, retry) must be idempotent, must ignore today's partial candle, and a run that starts after the live window must not produce a prediction. Task 5.
5. **An empty or one-day dashboard** (no settled days yet, one data point, all-null heatmap rows, a chart whose x-range is zero) must render a clear state, not a blank or broken page. Task 10.

Also pinned: an asset with too little history is omitted by every estimator without raising (Task 6).

---

## File Structure

```
assets.yaml                          settings + the editable asset list
requirements.txt                     runtime base deps
requirements-dev.txt                 adds pytest and the light estimators' deps
pytest.ini
bench/
  __init__.py
  config.py                          Asset, Settings, load_config
  store.py                           Store: predictions json, ledger/equity csv, runs.jsonl, SCHEMA marker
  data.py                            fetch, normalize, merge, update_prices, load_prices, stale_assets
  broker.py                          settle_estimator (the paper broker)
  scoring.py                         metrics, hit rate, luck test, sanity flag
  runner.py                          cut_history, run_estimator_day (shared by live and backfill)
  aggregate.py                       build_all -> site/data/*.json
  notify.py                          build_message, send, notify
  cli.py                             list | requirements | fetch | run | backfill | aggregate | notify
estimators/
  __init__.py
  base.py                            Prediction, Estimator
  registry.py                        REGISTRY metadata + build()
  controls/predict.py                AlwaysLong, RandomCoin, Persistence
  analog/predict.py                  candle-shape nearest-neighbour matching
  xgb_indicators/{predict.py,requirements.txt}
  candle_rules/predict.py            hammer / shooting star / engulfing rules
site/
  index.html  style.css  app.js  charts.js  lib.js  lib.test.js
tests/
  __init__.py  helpers.py  test_*.py
data/                                committed state (prices/, live/, backtest/)
.github/workflows/{daily.yml,backfill.yml}
docs/superpowers/{specs,plans}/
```

---

### Task 1: Repo skeleton, config, store

**Rulebook:** read ch 5 (`02-book/1-decisions-before-code/05-dependencies-licensing-provenance.md`) and ch 35 (`02-book/6-out-in-the-world/35-migration-versioning-and-compatibility.md`). Note in the commit message any rule that changed a step.

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `assets.yaml`, `bench/__init__.py`, `bench/config.py`, `bench/store.py`, `tests/__init__.py`, `tests/helpers.py`, `tests/test_config.py`, `tests/test_store.py`
- Test: `tests/test_config.py`, `tests/test_store.py`

**Interfaces:**
- Produces: `Asset(symbol, group, max_gap_days)`, `Settings` (fields below), `load_config(path) -> (Settings, list[Asset])`, `Store(root)` with `est_dir`, `save_prediction`, `load_predictions`, `load_equity`, `load_ledger`, `append_equity`, `append_ledger`, `record_run`, `load_runs`; constants `SCHEMA_VERSION`, `EQUITY_COLS`, `LEDGER_COLS`; exception `SchemaMismatch`.

- [ ] **Step 1: Check the toolchain and initialise the repo**

Run (Git Bash, from `C:\Claude Projects\Trading Bot Testing Grounds`):

```bash
python --version && git --version && node --version
git init
python -m venv .venv
source .venv/Scripts/activate
```

Expected: Python 3.11 or newer, git present. If `node` is missing, note it: Task 10 needs it (install Node LTS then, with the owner's OK). If Python is older than 3.11, stop and ask the owner to install 3.11+.

- [ ] **Step 2: Create the scaffolding files**

`.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
site/data/
data/cache/
node_modules/
```

`requirements.txt`:

```
pandas>=2.2
numpy>=1.26
PyYAML>=6
yfinance>=0.2.40
```

`requirements-dev.txt`:

```
-r requirements.txt
pytest>=8
xgboost>=2.0
scikit-learn>=1.4
```

`pytest.ini`:

```
[pytest]
pythonpath = .
testpaths = tests
```

`assets.yaml`:

```yaml
settings:
  start_equity: 10000
  cost_round_trip: 0.001
  trade_threshold: 0.001
  min_live_days: 60
  sanity_day_pct: 0.10
  sanity_week_pct: 0.50
  history_start: "2019-01-01"
assets:
  - {symbol: SPY,     group: stock,     max_gap_days: 5}
  - {symbol: QQQ,     group: stock,     max_gap_days: 5}
  - {symbol: AAPL,    group: stock,     max_gap_days: 5}
  - {symbol: MSFT,    group: stock,     max_gap_days: 5}
  - {symbol: NVDA,    group: stock,     max_gap_days: 5}
  - {symbol: AMZN,    group: stock,     max_gap_days: 5}
  - {symbol: GOOGL,   group: stock,     max_gap_days: 5}
  - {symbol: META,    group: stock,     max_gap_days: 5}
  - {symbol: TSLA,    group: stock,     max_gap_days: 5}
  - {symbol: JPM,     group: stock,     max_gap_days: 5}
  - {symbol: V,       group: stock,     max_gap_days: 5}
  - {symbol: XOM,     group: stock,     max_gap_days: 5}
  - {symbol: WMT,     group: stock,     max_gap_days: 5}
  - {symbol: JNJ,     group: stock,     max_gap_days: 5}
  - {symbol: AMD,     group: stock,     max_gap_days: 5}
  - {symbol: BTC-USD, group: crypto,    max_gap_days: 2}
  - {symbol: ETH-USD, group: crypto,    max_gap_days: 2}
  - {symbol: SOL-USD, group: crypto,    max_gap_days: 2}
  - {symbol: GLD,     group: commodity, max_gap_days: 5}
  - {symbol: SLV,     group: commodity, max_gap_days: 5}
  - {symbol: USO,     group: commodity, max_gap_days: 5}
```

Create empty `bench/__init__.py`, `tests/__init__.py`, `estimators/__init__.py`.

`tests/helpers.py`:

```python
from datetime import date, timedelta

import numpy as np
import pandas as pd


def candles(rows):
    """rows: (date, open, high, low, close) tuples -> candle DataFrame."""
    return pd.DataFrame(
        [
            {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1}
            for d, o, h, l, c in rows
        ]
    )


def random_walk(n, start="2024-01-01", seed=0, daily_vol=0.01):
    """n consecutive calendar days of synthetic candles, deterministic per seed."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, daily_vol, n)
    close = 100 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    d0 = date.fromisoformat(start)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(n)]
    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": 1000}
    )
```

- [ ] **Step 3: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from bench.config import Asset, load_config

ROOT = Path(__file__).resolve().parent.parent


def test_real_config_loads():
    settings, assets = load_config(ROOT / "assets.yaml")
    assert len(assets) == 21
    assert settings.start_equity == 10000
    assert settings.cost_round_trip == 0.001
    assert Asset("BTC-USD", "crypto", 2) in assets


def test_unknown_setting_rejected(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("settings: {bogus: 1}\nassets: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        load_config(p)


def test_duplicate_symbol_rejected(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text(
        "assets:\n  - {symbol: A, group: stock, max_gap_days: 5}\n"
        "  - {symbol: A, group: stock, max_gap_days: 5}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_config(p)
```

`tests/test_store.py`:

```python
import pytest

from bench.store import EQUITY_COLS, SchemaMismatch, Store


def test_prediction_roundtrip(tmp_path):
    s = Store(tmp_path / "live")
    payload = {"predictions": {"AAA": {"asof": "2026-01-02", "expected_return": 0.01}}}
    s.save_prediction("est", "2026-01-03", payload)
    assert s.load_predictions("est") == {"2026-01-03": payload}


def test_empty_loads_have_columns(tmp_path):
    s = Store(tmp_path / "live")
    eq = s.load_equity("est")
    assert list(eq.columns) == EQUITY_COLS and len(eq) == 0


def test_append_accumulates(tmp_path):
    s = Store(tmp_path / "live")
    row = {"date": "2026-01-05", "equity": 10100.0, "day_return": 0.01, "n_universe": 2, "n_traded": 1}
    s.append_equity("est", [row])
    s.append_equity("est", [{**row, "date": "2026-01-06"}])
    eq = s.load_equity("est")
    assert eq["date"].tolist() == ["2026-01-05", "2026-01-06"]


def test_runs_log(tmp_path):
    s = Store(tmp_path / "live")
    s.record_run("est", {"run_date": "2026-01-03", "status": "ok"})
    s.record_run("est", {"run_date": "2026-01-04", "status": "failed"})
    assert [r["status"] for r in s.load_runs("est")] == ["ok", "failed"]


def test_schema_mismatch_raises(tmp_path):
    root = tmp_path / "live"
    Store(root)
    (root / "SCHEMA").write_text("99\n")
    with pytest.raises(SchemaMismatch):
        Store(root)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/test_config.py tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.config'`

- [ ] **Step 5: Implement `bench/config.py` and `bench/store.py`**

`bench/config.py`:

```python
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Asset:
    symbol: str
    group: str  # stock | crypto | commodity
    max_gap_days: int  # how many days behind before the asset is reported stale


@dataclass(frozen=True)
class Settings:
    start_equity: float = 10000.0
    cost_round_trip: float = 0.001
    trade_threshold: float = 0.001
    min_live_days: int = 60
    sanity_day_pct: float = 0.10
    sanity_week_pct: float = 0.50
    history_start: str = "2019-01-01"


def load_config(path="assets.yaml"):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    given = raw.get("settings") or {}
    extra = set(given) - {f.name for f in fields(Settings)}
    if extra:
        raise ValueError(f"unknown settings: {sorted(extra)}")
    assets = [Asset(**a) for a in raw.get("assets", [])]
    symbols = [a.symbol for a in assets]
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate asset symbols")
    return Settings(**given), assets
```

`bench/store.py`:

```python
import json
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = 1
EQUITY_COLS = ["date", "equity", "day_return", "n_universe", "n_traded"]
LEDGER_COLS = [
    "settle_date", "asset", "asof", "entry", "exit", "expected_return",
    "traded", "gross_ret", "net_ret", "actual_cc", "hit",
]


class SchemaMismatch(RuntimeError):
    pass


class Store:
    """All files for one data set (live or backtest) under one root folder."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / "SCHEMA"
        if marker.exists():
            found = int(marker.read_text().strip())
            if found != SCHEMA_VERSION:
                raise SchemaMismatch(
                    f"{self.root} has schema {found}, code expects {SCHEMA_VERSION}"
                )
        else:
            marker.write_text(f"{SCHEMA_VERSION}\n")

    def est_dir(self, name):
        p = self.root / "estimators" / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_prediction(self, name, run_date, payload):
        d = self.est_dir(name) / "predictions"
        d.mkdir(exist_ok=True)
        text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
        (d / f"{run_date}.json").write_text(text, encoding="utf-8")

    def load_predictions(self, name):
        d = self.est_dir(name) / "predictions"
        out = {}
        for f in sorted(d.glob("*.json")):
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        return out

    def load_equity(self, name):
        return self._load(name, "equity.csv", EQUITY_COLS)

    def load_ledger(self, name):
        return self._load(name, "ledger.csv", LEDGER_COLS)

    def append_equity(self, name, rows):
        self._append(name, "equity.csv", EQUITY_COLS, rows)

    def append_ledger(self, name, rows):
        self._append(name, "ledger.csv", LEDGER_COLS, rows)

    def record_run(self, name, rec):
        with open(self.est_dir(name) / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def load_runs(self, name):
        p = self.est_dir(name) / "runs.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

    def _load(self, name, fname, cols):
        p = self.est_dir(name) / fname
        if not p.exists():
            return pd.DataFrame(columns=cols)
        df = pd.read_csv(p, dtype={"date": str, "settle_date": str, "asof": str})
        if list(df.columns) != cols:
            raise SchemaMismatch(f"{p} has columns {list(df.columns)}, expected {cols}")
        return df

    def _append(self, name, fname, cols, rows):
        if not rows:
            return
        new = pd.DataFrame(rows, columns=cols)
        old = self._load(name, fname, cols)
        out = new if old.empty else pd.concat([old, new], ignore_index=True)
        out.to_csv(self.est_dir(name) / fname, index=False, lineterminator="\n")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py tests/test_store.py -v`
Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "feat: repo skeleton, config loader and versioned data store"
```

---

### Task 2: Price data fetch and cache

**Rulebook:** read ch 19 (`02-book/3-the-build/19-external-apis-and-integrations.md`). Its rule: every external API is real, reachable, and has auth model, rate limit, pricing and licence recorded before code is written against it. Step 1 does that for yfinance.

**Files:**
- Create: `bench/data.py`, `docs/data-sources.md`, `tests/test_data.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Consumes: `Asset` from Task 1.
- Produces: `COLUMNS`, `normalize(raw) -> DataFrame`, `fetch_asset(symbol, start) -> DataFrame`, `merge_candles(old, new) -> DataFrame`, `update_prices(prices_dir, assets, start, fetch=fetch_asset) -> dict[str, str]`, `load_prices(prices_dir, assets) -> dict[str, DataFrame]`, `stale_assets(prices, assets, run_date) -> dict[str, int | None]`. Candle frames have columns `date` (ISO string), `open`, `high`, `low`, `close`, `volume`.

- [ ] **Step 1: Record the data source (chapter 19)**

Use context7 (`resolve-library-id` for `yfinance`, then `query-docs`) and the yfinance project page to confirm: it is an unofficial wrapper around Yahoo Finance's public endpoints; no API key; no published rate limit (it can throttle or break without notice); Yahoo's terms restrict use to personal use; licence Apache-2.0. Write `docs/data-sources.md` with those facts, today's date, and a fallback note ("if yfinance breaks: Stooq CSV for stocks and ETFs, a public exchange API for crypto; switching means replacing only `fetch_asset`"). Do not write facts you did not confirm; write "unconfirmed" instead.

- [ ] **Step 2: Write the failing tests**

`tests/test_data.py`:

```python
import pandas as pd
import pytest

from bench.config import Asset
from bench.data import (
    COLUMNS, load_prices, merge_candles, normalize, stale_assets, update_prices,
)
from tests.helpers import candles


def raw_frame():
    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-06"], tz="America/New_York")
    return pd.DataFrame(
        {"Open": [100.0, 101.0, 102.0], "High": [103.0, 104.0, 105.0],
         "Low": [99.0, 100.0, 101.0], "Close": [102.0, 103.0, 104.0],
         "Volume": [10, 11, 12]},
        index=idx,
    )


def test_normalize_uses_local_session_date_and_dedups():
    df = normalize(raw_frame())
    assert list(df.columns) == COLUMNS
    assert df["date"].tolist() == ["2026-01-05", "2026-01-06"]
    assert df["close"].tolist() == [102.0, 104.0]  # duplicate date keeps the last row


def test_normalize_drops_nan_and_nonpositive_rows():
    raw = raw_frame()
    raw.iloc[0, raw.columns.get_loc("Close")] = float("nan")
    raw.iloc[1, raw.columns.get_loc("Open")] = 0.0
    assert normalize(raw)["date"].tolist() == ["2026-01-06"]


def test_normalize_empty():
    assert list(normalize(pd.DataFrame()).columns) == COLUMNS


def test_merge_new_overrides_old_and_sorts():
    old = candles([("2026-01-05", 1, 1, 1, 1), ("2026-01-06", 2, 2, 2, 2)])
    new = candles([("2026-01-06", 9, 9, 9, 9), ("2026-01-07", 3, 3, 3, 3)])
    out = merge_candles(old, new)
    assert out["date"].tolist() == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert out["close"].tolist() == [1, 9, 3]


ASSETS = [Asset("AAA", "stock", 5), Asset("BBB", "crypto", 2)]


def test_update_first_fetch_uses_start_then_overlap(tmp_path):
    calls = []

    def fake(symbol, since):
        calls.append((symbol, since))
        return candles([("2026-01-05", 1, 1, 1, 1), ("2026-01-06", 2, 2, 2, 2)])

    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=fake)
    assert status == {"AAA": "ok", "BBB": "ok"}
    assert calls[0] == ("AAA", "2019-01-01")
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=fake)
    assert calls[2] == ("AAA", "2025-12-27")  # last date minus 10 days


def test_update_failure_keeps_cache(tmp_path):
    good = lambda s, since: candles([("2026-01-05", 1, 1, 1, 1)])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=good)
    before = (tmp_path / "AAA.csv").read_text()

    def boom(symbol, since):
        raise RuntimeError("rate limited")

    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=boom)
    assert status["AAA"].startswith("error: RuntimeError")
    assert (tmp_path / "AAA.csv").read_text() == before


def test_update_empty_fetch_is_an_error_not_a_wipe(tmp_path):
    good = lambda s, since: candles([("2026-01-05", 1, 1, 1, 1)])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=good)
    before = (tmp_path / "AAA.csv").read_text()
    empty = lambda s, since: pd.DataFrame(columns=COLUMNS)
    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=empty)
    assert "no rows" in status["AAA"]
    assert (tmp_path / "AAA.csv").read_text() == before


def test_load_prices_missing_file_is_empty(tmp_path):
    out = load_prices(tmp_path, ASSETS)
    assert len(out["AAA"]) == 0 and list(out["AAA"].columns) == COLUMNS


def test_stale_assets():
    prices = {
        "AAA": candles([("2026-01-01", 1, 1, 1, 1)]),  # 9 days behind cutoff 01-10
        "BBB": candles([("2026-01-07", 1, 1, 1, 1)]),  # 3 days behind, crypto limit 2
        "CCC": candles([("2026-01-10", 1, 1, 1, 1)]),  # fresh
    }
    assets = [Asset("AAA", "stock", 5), Asset("BBB", "crypto", 2), Asset("CCC", "stock", 5),
              Asset("DDD", "stock", 5)]
    out = stale_assets(prices, assets, "2026-01-11")
    assert out == {"AAA": 9, "BBB": 3, "DDD": None}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.data'`

- [ ] **Step 4: Implement `bench/data.py`**

```python
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

COLUMNS = ["date", "open", "high", "low", "close", "volume"]
PRICE_COLS = ["open", "high", "low", "close"]


def normalize(raw):
    """yfinance history frame -> candle frame with ISO session dates."""
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=COLUMNS)
    df = raw.rename(columns=str.lower)[PRICE_COLS + ["volume"]].copy()
    df.insert(0, "date", [ts.date().isoformat() for ts in df.index])
    df = df.dropna(subset=PRICE_COLS)
    df = df[(df[PRICE_COLS] > 0).all(axis=1)]
    return df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)


def fetch_asset(symbol, start):
    """The only function that touches the network. Replace this to change data source."""
    import yfinance as yf

    raw = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=True)
    return normalize(raw)


def merge_candles(old, new):
    both = new.copy() if len(old) == 0 else pd.concat([old, new], ignore_index=True)
    return both.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)


def _path(prices_dir, symbol):
    return Path(prices_dir) / f"{symbol}.csv"


def _read(path):
    if path.exists():
        return pd.read_csv(path, dtype={"date": str})
    return pd.DataFrame(columns=COLUMNS)


def load_prices(prices_dir, assets):
    return {a.symbol: _read(_path(prices_dir, a.symbol)) for a in assets}


def update_prices(prices_dir, assets, start, fetch=fetch_asset):
    """Refresh every asset's cache. A failure or an empty result never touches the cache."""
    Path(prices_dir).mkdir(parents=True, exist_ok=True)
    status = {}
    for a in assets:
        path = _path(prices_dir, a.symbol)
        old = _read(path)
        since = start
        if not old.empty:
            since = (date.fromisoformat(old["date"].iloc[-1]) - timedelta(days=10)).isoformat()
        try:
            new = fetch(a.symbol, since)
            if new is None or len(new) == 0:
                raise ValueError("no rows returned")
            merge_candles(old, new).to_csv(path, index=False, lineterminator="\n")
            status[a.symbol] = "ok"
        except Exception as e:  # recorded, never raised: one bad asset must not stop the run
            status[a.symbol] = f"error: {type(e).__name__}: {e}"
    return status


def stale_assets(prices, assets, run_date):
    """Assets whose newest completed candle is too old. None means no data at all."""
    cutoff = date.fromisoformat(run_date) - timedelta(days=1)
    out = {}
    for a in assets:
        df = prices.get(a.symbol)
        seen = df[df["date"] <= cutoff.isoformat()] if df is not None and len(df) else None
        if seen is None or len(seen) == 0:
            out[a.symbol] = None
            continue
        gap = (cutoff - date.fromisoformat(seen["date"].iloc[-1])).days
        if gap > a.max_gap_days:
            out[a.symbol] = gap
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_data.py -v`
Expected: 9 passed

- [ ] **Step 6: Smoke-test the real fetch once**

```bash
python - <<'EOF'
from bench.data import fetch_asset
df = fetch_asset("SPY", "2026-09-01")
print(df.tail(3)); assert len(df) > 5 and df["close"].gt(0).all()
df = fetch_asset("BTC-USD", "2026-09-01"); print(df.tail(2))
EOF
```

Expected: recent SPY and BTC-USD candles print. If this fails, stop and report: every later task depends on live data. Update `docs/data-sources.md` with what was observed.

- [ ] **Step 7: Commit**

```bash
git add bench/data.py docs/data-sources.md tests/test_data.py
git commit -m "feat: price fetch and cache that never corrupts on bad data"
```

---

### Task 3: Paper broker

**Rulebook:** read ch 31 (`02-book/5-the-qualities/31-correctness-and-testing.md`). Every expected number below is hand-calculated; keep them that way.

**Files:**
- Create: `bench/broker.py`, `tests/test_broker.py`
- Test: `tests/test_broker.py`

**Interfaces:**
- Consumes: `Store` (Task 1), `Settings` (Task 1), candle frames (Task 2).
- Produces: `settle_estimator(store, name, prices, settings) -> int` (number of newly settled days). Reads the estimator's saved predictions, settles every target session that now has a completed candle, appends to `ledger.csv` and `equity.csv`. A saved prediction is `{"asof": <last candle date when predicted>, "expected_return": float, ...}` inside `payload["predictions"][asset]`.

**How settlement works (read before coding):** a prediction made with `asof = L` for an asset targets the asset's *next candle after L*. Entry = that candle's open, exit = its close. Return = `close/open - 1 - cost` if `expected_return > trade_threshold`, else 0 (cash). For each settled date T the account's day return is the sum of trade returns divided by the number of assets that have a candle on T (assets with no prediction count as cash). Equity compounds: `equity *= 1 + day_return`. Dates at or before the last settled date are skipped, which makes settling idempotent.

- [ ] **Step 1: Write the failing tests**

`tests/test_broker.py`:

```python
import pytest

from bench.broker import settle_estimator
from bench.config import Settings
from bench.store import Store
from tests.helpers import candles

S = Settings()  # $10,000, cost 0.001, threshold 0.001


def pred(asof, exp):
    return {"asof": asof, "expected_return": exp, "confidence": None, "path": None}


def save(store, name, run_date, preds):
    store.save_prediction(name, run_date, {"predictions": preds})


def two_day_prices():
    return {
        "AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)]),
    }


def test_single_winning_trade(tmp_path):
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    assert settle_estimator(st, "e", two_day_prices(), S) == 1
    eq = st.load_equity("e").iloc[0]
    assert eq["date"] == "2026-01-05"
    assert eq["day_return"] == pytest.approx(0.019)  # 102/100 - 1 - 0.001
    assert eq["equity"] == pytest.approx(10190.0)
    led = st.load_ledger("e").iloc[0]
    assert (led["entry"], led["exit"], led["traded"]) == (100, 102, 1)
    assert led["actual_cc"] == pytest.approx(0.02)  # 102 / prev close 100 - 1
    assert led["hit"] == 1


def test_cash_asset_dilutes_the_split(tmp_path):
    prices = two_day_prices()
    prices["BBB"] = candles([("2026-01-02", 50, 51, 49, 50), ("2026-01-05", 50, 51, 48, 49)])
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})  # no prediction for BBB
    settle_estimator(st, "e", prices, S)
    eq = st.load_equity("e").iloc[0]
    assert eq["n_universe"] == 2 and eq["n_traded"] == 1
    assert eq["day_return"] == pytest.approx(0.0095)
    assert eq["equity"] == pytest.approx(10095.0)


def test_asset_without_a_session_is_not_in_the_split(tmp_path):
    prices = two_day_prices()
    prices["BBB"] = candles([("2026-01-02", 50, 51, 49, 50)])  # holiday: no candle on 01-05
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    settle_estimator(st, "e", prices, S)
    eq = st.load_equity("e").iloc[0]
    assert eq["n_universe"] == 1
    assert eq["equity"] == pytest.approx(10190.0)


def test_below_threshold_stays_in_cash_but_is_still_scored(tmp_path):
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.0005)})
    settle_estimator(st, "e", two_day_prices(), S)
    eq = st.load_equity("e").iloc[0]
    assert eq["equity"] == pytest.approx(10000.0) and eq["n_traded"] == 0
    led = st.load_ledger("e").iloc[0]
    assert led["traded"] == 0 and led["net_ret"] == 0 and led["hit"] == 1


def test_wrong_direction_is_a_miss_and_a_loss_compounds(tmp_path):
    prices = {
        "AAA": candles([
            ("2026-01-02", 99, 101, 98, 100),
            ("2026-01-05", 100, 103, 99, 102),
            ("2026-01-06", 100, 101, 98, 99),
        ])
    }
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    save(st, "e", "2026-01-06", {"AAA": pred("2026-01-05", 0.01)})
    assert settle_estimator(st, "e", prices, S) == 2
    eq = st.load_equity("e")
    # day 2: open 100 close 99 -> -0.01 - 0.001 = -0.011 ; 10190 * 0.989
    assert eq["equity"].iloc[1] == pytest.approx(10077.91)
    assert st.load_ledger("e")["hit"].tolist() == [1, 0]


def test_settling_twice_changes_nothing(tmp_path):
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    settle_estimator(st, "e", two_day_prices(), S)
    assert settle_estimator(st, "e", two_day_prices(), S) == 0
    assert len(st.load_equity("e")) == 1 and len(st.load_ledger("e")) == 1


def test_no_predictions_no_rows(tmp_path):
    st = Store(tmp_path)
    assert settle_estimator(st, "e", two_day_prices(), S) == 0
    assert st.load_equity("e").empty


def test_prediction_without_a_completed_target_candle_waits(tmp_path):
    prices = {"AAA": candles([("2026-01-02", 99, 101, 98, 100)])}
    st = Store(tmp_path)
    save(st, "e", "2026-01-03", {"AAA": pred("2026-01-02", 0.01)})
    assert settle_estimator(st, "e", prices, S) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_broker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.broker'`

- [ ] **Step 3: Implement `bench/broker.py`**

```python
def net_return(entry, exit_, cost):
    return exit_ / entry - 1.0 - cost


def should_trade(expected_return, threshold):
    return expected_return > threshold


def _targets(prices):
    """(asset, asof) -> (target_date, open, close, previous_close) for every consecutive candle pair."""
    out = {}
    for asset, df in prices.items():
        d, o, c = df["date"].tolist(), df["open"].tolist(), df["close"].tolist()
        for i in range(1, len(d)):
            out[(asset, d[i - 1])] = (d[i], o[i], c[i], c[i - 1])
    return out


def _sessions_per_date(prices):
    counts = {}
    for df in prices.values():
        for d in df["date"]:
            counts[d] = counts.get(d, 0) + 1
    return counts


def settle_estimator(store, name, prices, settings):
    by_key = {}
    saved = store.load_predictions(name)  # read the prediction files once
    for run_date in sorted(saved):
        payload = saved[run_date]
        for asset, p in payload["predictions"].items():
            by_key[(asset, p["asof"])] = p

    targets = _targets(prices)
    days = {}
    for (asset, asof), p in by_key.items():
        if (asset, asof) in targets:
            t, o, c, prev_c = targets[(asset, asof)]
            days.setdefault(t, {})[asset] = (p, o, c, prev_c)

    equity = store.load_equity(name)
    last_done = equity["date"].iloc[-1] if len(equity) else ""
    eq = float(equity["equity"].iloc[-1]) if len(equity) else float(settings.start_equity)
    sessions = _sessions_per_date(prices)

    ledger_rows, equity_rows = [], []
    for t in sorted(days):
        if t <= last_done:
            continue
        total, n_traded = 0.0, 0
        for asset, (p, o, c, prev_c) in sorted(days[t].items()):
            exp = p["expected_return"]
            traded = should_trade(exp, settings.trade_threshold)
            gross = c / o - 1.0
            net = net_return(o, c, settings.cost_round_trip) if traded else 0.0
            actual_cc = c / prev_c - 1.0
            hit = None if (exp == 0 or actual_cc == 0) else int((exp > 0) == (actual_cc > 0))
            total += net
            n_traded += int(traded)
            ledger_rows.append({
                "settle_date": t, "asset": asset, "asof": p["asof"], "entry": o, "exit": c,
                "expected_return": exp, "traded": int(traded), "gross_ret": gross,
                "net_ret": net, "actual_cc": actual_cc, "hit": hit,
            })
        n_universe = sessions[t]
        day_return = total / n_universe
        eq *= 1.0 + day_return
        equity_rows.append({
            "date": t, "equity": eq, "day_return": day_return,
            "n_universe": n_universe, "n_traded": n_traded,
        })
        last_done = t

    store.append_ledger(name, ledger_rows)
    store.append_equity(name, equity_rows)
    return len(equity_rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broker.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add bench/broker.py tests/test_broker.py
git commit -m "feat: paper broker with continuous accounts and idempotent settlement"
```

---

### Task 4: Scoring

**Files:**
- Create: `bench/scoring.py`, `tests/test_scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Produces: `total_return(equities, start) -> float`, `max_drawdown(equities) -> float` (negative or 0), `worst_day(day_returns) -> float`, `hit_rate(flags) -> float | None`, `sign_flip_pvalue(diffs, n_iter=5000, seed=0) -> float`, `edge_vs_control(est: dict[str, float], control: dict[str, float]) -> {"n", "edge", "p_value"}` (both dicts map date to day return), `sanity_flag(day_returns, day_pct, week_pct) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_scoring.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.scoring'`

- [ ] **Step 3: Implement `bench/scoring.py`**

```python
import math

import numpy as np


def total_return(equities, start):
    return equities[-1] / start - 1.0 if equities else 0.0


def max_drawdown(equities):
    peak, worst = -math.inf, 0.0
    for e in equities:
        peak = max(peak, e)
        worst = min(worst, e / peak - 1.0)
    return worst


def worst_day(day_returns):
    return min(day_returns) if day_returns else 0.0


def hit_rate(flags):
    kept = [f for f in flags if f is not None and f == f]
    return sum(kept) / len(kept) if kept else None


def sign_flip_pvalue(diffs, n_iter=5000, seed=0):
    """One-sided: how often random sign flips give a mean at least as large as observed."""
    d = np.asarray(diffs, dtype=float)
    if len(d) < 2 or not d.any():
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_iter, len(d)))
    perm = (signs * d).mean(axis=1)
    return float((np.sum(perm >= d.mean()) + 1) / (n_iter + 1))


def edge_vs_control(est, control):
    common = sorted(set(est) & set(control))
    diffs = [est[d] - control[d] for d in common]
    return {
        "n": len(common),
        "edge": float(np.mean(diffs)) if diffs else 0.0,
        "p_value": sign_flip_pvalue(diffs),
    }


def sanity_flag(day_returns, day_pct, week_pct):
    """Gains this large are far more likely a bug or a data leak than skill."""
    if not day_returns:
        return False
    if day_returns[-1] > day_pct:
        return True
    week = 1.0
    for r in day_returns[-7:]:
        week *= 1.0 + r
    return week - 1.0 > week_pct
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scoring.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add bench/scoring.py tests/test_scoring.py
git commit -m "feat: scoring metrics, luck test and sanity flag"
```

---

### Task 5: Estimator contract, controls, registry and the day runner

**Rulebook:** read ch 43 (`02-book/3-the-build/43-background-jobs.md`: idempotent, overlapping scheduled runs) and ch 24 (`02-book/4-the-states-nobody-asks-for/24-errors.md`: failures are recorded with a reason, never swallowed). This task is the core of the project; the tests here are the honesty guarantees.

**Files:**
- Create: `estimators/base.py`, `estimators/registry.py`, `estimators/controls/__init__.py`, `estimators/controls/predict.py`, `bench/runner.py`, `tests/test_runner.py`, `tests/test_controls.py`
- Test: `tests/test_runner.py`, `tests/test_controls.py`

**Interfaces:**
- Consumes: `Store`, `Settings`, `settle_estimator`, candle frames.
- Produces:
  - `Prediction(expected_return: float, confidence: float | None = None, path: list[float] | None = None)` (frozen dataclass; `path` is predicted closes for the next sessions).
  - `Estimator` base class: attributes `name: str`, `backfill_stride: int = 1`; method `predict(history: dict[str, DataFrame], assets: list[str]) -> dict[str, Prediction]`. `history` holds candles up to the cutoff only; `assets` lists the assets that need a prediction; an estimator omits an asset it cannot predict.
  - `REGISTRY: dict[str, dict]` with keys `target` (`"module:Class"`), `label`, `kind` (`control|pattern|ml|pretrained`), `source`, `license`, `original_code` (bool), optional `requirements` (path); `names() -> list[str]`; `build(name) -> Estimator`.
  - `cutoff_for(run_date) -> str`, `cut_history(prices, run_date) -> dict`, `live_window_ok(run_date, now) -> bool`, `assets_needing_prediction(store, name, history, run_date) -> list[str]`, `run_estimator_day(store, estimator, prices, run_date, settings, now=None) -> dict` (the run record).

- [ ] **Step 1: Write the estimator base and registry**

`estimators/base.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Prediction:
    expected_return: float  # expected close-to-close return of the asset's next session
    confidence: float | None = None
    path: list[float] | None = None  # predicted closes for the next sessions, if the model forecasts further


class Estimator:
    name = ""
    backfill_stride = 1  # backfill runs the estimator on every Nth day; the rest stay in cash

    def predict(self, history, assets):
        """history: {asset: candle DataFrame up to the cutoff}; return {asset: Prediction}."""
        raise NotImplementedError
```

`estimators/registry.py`:

```python
import importlib

REGISTRY = {
    "control_always_long": {
        "target": "estimators.controls.predict:AlwaysLong",
        "label": "Always long (control)", "kind": "control",
        "source": "Baseline: buys every asset every day and pays the same costs",
        "license": "own code", "original_code": False,
    },
    "control_random": {
        "target": "estimators.controls.predict:RandomCoin",
        "label": "Random coin (control)", "kind": "control",
        "source": "Baseline: a deterministic coin flip per asset per day",
        "license": "own code", "original_code": False,
    },
    "control_persistence": {
        "target": "estimators.controls.predict:Persistence",
        "label": "Tomorrow = today (control)", "kind": "control",
        "source": "Baseline: predicts that the next return equals the last return",
        "license": "own code", "original_code": False,
    },
}


def names():
    return list(REGISTRY)


def build(name):
    module, cls = REGISTRY[name]["target"].split(":")
    return getattr(importlib.import_module(module), cls)()
```

`estimators/controls/__init__.py`: empty file.

`estimators/controls/predict.py`:

```python
import hashlib

from estimators.base import Estimator, Prediction


class AlwaysLong(Estimator):
    name = "control_always_long"

    def predict(self, history, assets):
        return {a: Prediction(1.0) for a in assets if len(history[a])}


class RandomCoin(Estimator):
    name = "control_random"

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if not len(df):
                continue
            digest = hashlib.sha256(f"{a}:{df['date'].iloc[-1]}".encode()).digest()
            out[a] = Prediction(1.0 if digest[0] % 2 == 0 else -1.0)
        return out


class Persistence(Estimator):
    name = "control_persistence"

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if len(df) < 2:
                continue
            out[a] = Prediction(float(df["close"].iloc[-1] / df["close"].iloc[-2] - 1.0))
        return out
```

- [ ] **Step 2: Write the failing runner tests**

`tests/test_runner.py`:

```python
import json
import math
from datetime import datetime, timezone

import pytest

from bench.config import Settings
from bench.runner import (
    assets_needing_prediction, cut_history, cutoff_for, live_window_ok, run_estimator_day,
)
from bench.store import Store
from estimators.base import Estimator, Prediction
from tests.helpers import candles, random_walk

S = Settings()


class Spy(Estimator):
    name = "spy"

    def __init__(self):
        self.seen = {}
        self.asked = []

    def predict(self, history, assets):
        self.seen = {a: df["date"].max() for a, df in history.items() if len(df)}
        self.asked = list(assets)
        return {a: Prediction(0.01) for a in assets if len(history[a])}


class Bad(Estimator):
    name = "bad"

    def __init__(self, value):
        self.value = value

    def predict(self, history, assets):
        return {a: Prediction(self.value) for a in assets if len(history[a])}


class Boom(Estimator):
    name = "boom"

    def predict(self, history, assets):
        raise RuntimeError("model exploded")


class Extra(Estimator):
    name = "extra"

    def predict(self, history, assets):
        return {"NOT_ASKED": Prediction(0.5), **{a: Prediction(0.01) for a in assets if len(history[a])}}


def test_cutoff_is_the_day_before():
    assert cutoff_for("2026-01-06") == "2026-01-05"


def test_estimator_never_sees_the_run_day_or_later(tmp_path):
    prices = {"AAA": candles([
        ("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1),
        ("2026-01-06", 1, 1, 1, 1),  # today's partial candle: must be invisible
        ("2026-01-07", 1, 1, 1, 1),
    ])}
    spy = Spy()
    run_estimator_day(Store(tmp_path), spy, prices, "2026-01-06", S)
    assert spy.seen == {"AAA": "2026-01-05"}


def test_prediction_is_saved_with_asof(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    rec = run_estimator_day(st, Spy(), prices, "2026-01-06", S)
    assert rec["status"] == "ok" and rec["n_predictions"] == 1
    saved = st.load_predictions("spy")["2026-01-06"]["predictions"]["AAA"]
    assert saved["asof"] == "2026-01-05" and saved["expected_return"] == 0.01


def test_rerun_same_day_is_idempotent(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": random_walk(30, "2026-01-01")}
    run_estimator_day(st, Spy(), prices, "2026-01-31", S)
    first = json.dumps(st.load_predictions("spy"), sort_keys=True)
    run_estimator_day(st, Spy(), prices, "2026-01-31", S)
    assert json.dumps(st.load_predictions("spy"), sort_keys=True) == first


def test_weekend_stock_is_not_repredicted_but_crypto_is(tmp_path):
    # 2026-01-02 is a Friday. STK has no weekend candles; CRY trades every day.
    stk = candles([("2025-12-31", 1, 1, 1, 1), ("2026-01-02", 1, 1, 1, 1)])
    cry = candles([("2026-01-01", 1, 1, 1, 1), ("2026-01-02", 1, 1, 1, 1), ("2026-01-03", 1, 1, 1, 1)])
    prices = {"STK": stk, "CRY": cry}
    st = Store(tmp_path)
    sat, sun = Spy(), Spy()
    run_estimator_day(st, sat, prices, "2026-01-03", S)   # Saturday: cutoff Friday
    assert sorted(sat.asked) == ["CRY", "STK"]
    run_estimator_day(st, sun, prices, "2026-01-04", S)   # Sunday: cutoff Saturday
    assert sun.asked == ["CRY"]


def test_non_finite_output_is_a_recorded_failure_with_no_prediction(tmp_path):
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    for value in (math.nan, math.inf):
        st = Store(tmp_path / str(value))
        rec = run_estimator_day(st, Bad(value), prices, "2026-01-06", S)
        assert rec["status"] == "failed" and "non-finite" in rec["error"]
        assert st.load_predictions("bad") == {}
        assert st.load_runs("bad")[-1]["status"] == "failed"


def test_exception_is_recorded_not_raised(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1)])}
    rec = run_estimator_day(st, Boom(), prices, "2026-01-06", S)
    assert rec["status"] == "failed" and "model exploded" in rec["error"]
    assert st.load_predictions("boom") == {}


def test_assets_nobody_asked_for_are_ignored(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    run_estimator_day(st, Extra(), prices, "2026-01-06", S)
    assert list(st.load_predictions("extra")["2026-01-06"]["predictions"]) == ["AAA"]


def test_live_window():
    d = "2026-01-06"
    ok = datetime(2026, 1, 6, 0, 40, tzinfo=timezone.utc)
    late = datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)
    early = datetime(2026, 1, 5, 23, 0, tzinfo=timezone.utc)
    assert live_window_ok(d, ok) and not live_window_ok(d, late) and not live_window_ok(d, early)


def test_late_run_settles_but_does_not_predict(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([("2026-01-02", 1, 1, 1, 1), ("2026-01-05", 1, 1, 1, 1)])}
    late = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)
    rec = run_estimator_day(st, Spy(), prices, "2026-01-06", S, now=late)
    assert rec["status"] == "skipped_late"
    assert st.load_predictions("spy") == {}


def test_settles_before_predicting(tmp_path):
    st = Store(tmp_path)
    prices = {"AAA": candles([
        ("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102),
    ])}
    run_estimator_day(st, Spy(), prices, "2026-01-03", S)   # predicts for the 5th
    run_estimator_day(st, Spy(), prices, "2026-01-06", S)   # settles the 5th
    assert len(st.load_equity("spy")) == 1
    assert st.load_equity("spy")["equity"].iloc[0] == pytest.approx(10190.0)
```

`tests/test_controls.py`:

```python
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
    assert out["AAA"].expected_return == 0.02
    assert Persistence().predict({"AAA": df.iloc[:1]}, ["AAA"]) == {}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_runner.py tests/test_controls.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.runner'`

- [ ] **Step 4: Implement `bench/runner.py`**

```python
import math
from datetime import date, datetime, timedelta, timezone

from bench.broker import settle_estimator
from bench.store import SCHEMA_VERSION

LIVE_WINDOW_HOURS = 6


def cutoff_for(run_date):
    return (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()


def cut_history(prices, run_date):
    """Only candles dated before the run date. This is the no-look-ahead guarantee."""
    cutoff = cutoff_for(run_date)
    return {a: df[df["date"] <= cutoff].reset_index(drop=True) for a, df in prices.items()}


def live_window_ok(run_date, now):
    start = datetime.fromisoformat(f"{run_date}T00:00:00+00:00")
    return start <= now <= start + timedelta(hours=LIVE_WINDOW_HOURS)


def assets_needing_prediction(store, name, history, run_date):
    """Assets whose newest candle has not been predicted by an earlier run."""
    earlier = set()
    for rd, payload in store.load_predictions(name).items():
        if rd < run_date:
            for asset, p in payload["predictions"].items():
                earlier.add((asset, p["asof"]))
    return [
        a for a, df in history.items()
        if len(df) and (a, df["date"].iloc[-1]) not in earlier
    ]


def _validate(asset, p):
    if not math.isfinite(p.expected_return):
        raise ValueError(f"non-finite expected_return for {asset}")
    if p.confidence is not None and not math.isfinite(p.confidence):
        raise ValueError(f"non-finite confidence for {asset}")
    if p.path is not None and not all(math.isfinite(x) for x in p.path):
        raise ValueError(f"non-finite path for {asset}")


def run_estimator_day(store, estimator, prices, run_date, settings, now=None):
    """Settle everything that can be settled, then predict. Used by live runs and backfill.

    now=None means a backtest replay: the live-window check is skipped.
    """
    name = estimator.name
    history = cut_history(prices, run_date)
    settle_estimator(store, name, history, settings)

    rec = {"run_date": run_date, "estimator": name}
    if now is not None and not live_window_ok(run_date, now):
        rec.update(status="skipped_late", error="run started outside the live window")
        store.record_run(name, rec)
        return rec

    need = assets_needing_prediction(store, name, history, run_date)
    try:
        raw = estimator.predict(history, list(need)) if need else {}
        preds = {}
        for asset, p in raw.items():
            if asset not in need:
                continue
            _validate(asset, p)
            preds[asset] = {
                "asof": history[asset]["date"].iloc[-1],
                "expected_return": float(p.expected_return),
                "confidence": None if p.confidence is None else float(p.confidence),
                "path": None if p.path is None else [float(x) for x in p.path],
            }
        payload = {
            "schema_version": SCHEMA_VERSION, "estimator": name, "run_date": run_date,
            "created_at": None if now is None else now.astimezone(timezone.utc).isoformat(),
            "predictions": preds,
        }
        store.save_prediction(name, run_date, payload)
        rec.update(status="ok", n_predictions=len(preds))
    except Exception as e:  # an estimator may fail; the bench must not
        rec.update(status="failed", error=f"{type(e).__name__}: {e}")
    store.record_run(name, rec)
    return rec
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_runner.py tests/test_controls.py -v`
Expected: 16 passed

- [ ] **Step 6: Commit**

```bash
git add estimators bench/runner.py tests/test_runner.py tests/test_controls.py
git commit -m "feat: estimator contract, controls and the shared day runner"
```

---

### Task 6: First real estimators and the contract test

**Files:**
- Create: `estimators/analog/__init__.py`, `estimators/analog/predict.py`, `estimators/xgb_indicators/__init__.py`, `estimators/xgb_indicators/predict.py`, `estimators/xgb_indicators/requirements.txt`, `estimators/candle_rules/__init__.py`, `estimators/candle_rules/predict.py`, `tests/test_estimator_contract.py`, `tests/test_analog.py`, `tests/test_candle_rules.py`
- Modify: `estimators/registry.py` (add three entries)
- Test: the three new test files

**Interfaces:**
- Consumes: `Estimator`, `Prediction`, `REGISTRY`.
- Produces: registry names `analog`, `xgb_indicators`, `candle_rules`. The contract test parametrizes over every registry name whose dependencies are importable, so every estimator added later is checked automatically.

**The contract every estimator must satisfy** (enforced by `tests/test_estimator_contract.py`): returns finite predictions only for assets it was asked about; omits (does not crash on) assets with too little history; is deterministic; does not mutate its input; contains no network access (no `yfinance` or `requests` in its source).

- [ ] **Step 1: Write the failing contract test**

`tests/test_estimator_contract.py`:

```python
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
```

`tests/test_analog.py`:

```python
import numpy as np
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
```

`tests/test_candle_rules.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_estimator_contract.py tests/test_analog.py tests/test_candle_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'estimators.analog'` (the contract test passes for the controls and skips for the rest).

- [ ] **Step 3: Implement the analog estimator**

`estimators/analog/predict.py` (empty `__init__.py` next to it):

```python
import numpy as np

from estimators.base import Estimator, Prediction


def _windows(df, k):
    """Row j describes candles j..j+k-1 as (body, upper wick, lower wick) relative to the open."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    base = np.column_stack([
        (c - o) / o,
        (h - np.maximum(o, c)) / o,
        (np.minimum(o, c) - l) / o,
    ])
    n = len(df)
    return np.hstack([base[i:n - k + 1 + i] for i in range(k)])


class Analog(Estimator):
    """Find the past stretches whose last few candles looked most like today's, average what came next.

    The idea comes from historical pattern-matching tools such as CandleEdge. This is our own
    small implementation of it, so it is a reimplementation, not the original code.
    """

    name = "analog"

    def __init__(self, window=3, neighbours=30, min_rows=250):
        self.window, self.neighbours, self.min_rows = window, neighbours, min_rows

    def predict(self, history, assets):
        k, out = self.window, {}
        for a in assets:
            df = history[a]
            if len(df) < self.min_rows:
                continue
            rows = _windows(df, k)
            past, query = rows[:-1], rows[-1]
            close = df["close"].to_numpy(float)
            nxt = close[k:] / close[k - 1:-1] - 1.0  # what followed each past window
            sd = past.std(axis=0) + 1e-12
            dist = np.linalg.norm((past - query) / sd, axis=1)
            idx = np.argsort(dist, kind="stable")[: self.neighbours]
            mean = float(nxt[idx].mean())
            agree = float((np.sign(nxt[idx]) == np.sign(mean)).mean())
            out[a] = Prediction(mean, agree)
        return out
```

- [ ] **Step 4: Implement the candlestick rules estimator**

`estimators/candle_rules/predict.py` (empty `__init__.py` next to it):

```python
from estimators.base import Estimator, Prediction

CALL = 0.002  # fixed size of the call; the rules say direction, not magnitude


def _signal(o, h, l, c):
    """+1 bullish, -1 bearish, 0 nothing. Arrays hold the last 5 candles, oldest first."""
    rng = h[-1] - l[-1]
    body = abs(c[-1] - o[-1])
    upper = h[-1] - max(o[-1], c[-1])
    lower = min(o[-1], c[-1]) - l[-1]
    down, up = c[-2] < c[-5], c[-2] > c[-5]
    if rng > 0 and body <= 0.3 * rng:
        if down and lower >= 2 * body and upper <= 0.1 * rng:
            return 1  # hammer after a decline
        if up and upper >= 2 * body and lower <= 0.1 * rng:
            return -1  # shooting star after a rise
    prev_red, prev_green = c[-2] < o[-2], c[-2] > o[-2]
    cur_green, cur_red = c[-1] > o[-1], c[-1] < o[-1]
    if prev_red and cur_green and o[-1] <= c[-2] and c[-1] >= o[-2]:
        return 1  # bullish engulfing
    if prev_green and cur_red and o[-1] >= c[-2] and c[-1] <= o[-2]:
        return -1  # bearish engulfing
    return 0


class CandleRules(Estimator):
    name = "candle_rules"

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if len(df) < 5:
                continue
            tail = df.tail(5)
            o, h, l, c = (tail[x].to_numpy(float) for x in ("open", "high", "low", "close"))
            out[a] = Prediction(CALL * _signal(o, h, l, c))
        return out
```

- [ ] **Step 5: Implement the XGBoost estimator**

`estimators/xgb_indicators/requirements.txt`:

```
xgboost>=2.0
scikit-learn>=1.4
```

`estimators/xgb_indicators/predict.py` (empty `__init__.py` next to it):

```python
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from estimators.base import Estimator, Prediction

FEATURES = [
    "ret1", "ret2", "ret3", "ret4", "ret5", "rsi14", "sma20", "sma50", "vol20", "range", "body",
]


def _features(df):
    c, o = df["close"].astype(float), df["open"].astype(float)
    h, l = df["high"].astype(float), df["low"].astype(float)
    r = c.pct_change()
    f = pd.DataFrame({f"ret{k}": r.shift(k - 1) for k in range(1, 6)})
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-12))
    f["sma20"] = c / c.rolling(20).mean() - 1
    f["sma50"] = c / c.rolling(50).mean() - 1
    f["vol20"] = r.rolling(20).std()
    f["range"] = (h - l) / c
    f["body"] = (c - o) / o
    f["target"] = r.shift(-1)  # the next session's close-to-close return
    return f


class XgbIndicators(Estimator):
    """Gradient-boosted trees on common technical indicators, pooled across assets.

    Retrained from the truncated history on every run (walk-forward by construction).
    """

    name = "xgb_indicators"

    def __init__(self, min_rows=120, min_train=500):
        self.min_rows, self.min_train = min_rows, min_train

    def predict(self, history, assets):
        frames = {a: _features(df) for a, df in history.items() if len(df) >= self.min_rows}
        train = pd.concat(
            [f.dropna(subset=FEATURES + ["target"]) for f in frames.values()], ignore_index=True
        ) if frames else pd.DataFrame()
        if len(train) < self.min_train:
            return {}
        model = XGBRegressor(
            n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8,
            tree_method="hist", random_state=0, n_jobs=1,
        )
        model.fit(train[FEATURES].to_numpy(float), train["target"].to_numpy(float))
        out = {}
        for a in assets:
            if a not in frames:
                continue
            last = frames[a].iloc[-1][FEATURES]
            if last.isna().any():
                continue
            out[a] = Prediction(float(model.predict(np.array([last.to_numpy(float)]))[0]))
        return out
```

- [ ] **Step 6: Register the three estimators**

Edit `estimators/registry.py`: add these entries inside `REGISTRY` after `control_persistence`:

```python
    "analog": {
        "target": "estimators.analog.predict:Analog",
        "label": "Analog candle matching", "kind": "pattern",
        "source": "Idea from CandleEdge-style historical pattern matching; our own reimplementation",
        "license": "own code", "original_code": False,
    },
    "candle_rules": {
        "target": "estimators.candle_rules.predict:CandleRules",
        "label": "Candlestick pattern rules", "kind": "pattern",
        "source": "Textbook rules: hammer, shooting star, engulfing; our own implementation",
        "license": "own code", "original_code": False,
    },
    "xgb_indicators": {
        "target": "estimators.xgb_indicators.predict:XgbIndicators",
        "label": "XGBoost on indicators", "kind": "ml",
        "source": "XGBoost regression on RSI, moving averages and recent returns; our own implementation",
        "license": "own code (uses xgboost, Apache-2.0)", "original_code": False,
        "requirements": "estimators/xgb_indicators/requirements.txt",
    },
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest -v`
Expected: all tests pass (the XGBoost contract test takes a few seconds). If a hand-built candle fixture in `test_candle_rules.py` does not produce the expected signal, fix the fixture numbers to match the rule definition in `_signal`, not the rule.

- [ ] **Step 8: Commit**

```bash
git add estimators tests
git commit -m "feat: analog, candlestick-rule and XGBoost estimators with a shared contract test"
```

---

### Task 7: Command line

**Files:**
- Create: `bench/cli.py`, `tests/test_cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m bench.cli <command>`; function `main(argv=None, now=None) -> int` (`now` injects the clock for tests). Commands: `list` (prints a JSON array of registry names), `requirements --estimator N` (prints that estimator's requirements path or an empty line), `fetch`, `run --estimator N [--run-date D]`, `backfill --estimator N [--days 365] [--end D]`, `aggregate [--run-date D]`, `notify [--run-date D] [--failure]`. Environment overrides for tests: `BENCH_DATA` (default `data`), `BENCH_ASSETS` (default `assets.yaml`), `BENCH_SITE` (default `site`). `aggregate` and `notify` import lazily from modules written in Tasks 8 and 12.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'cli' from 'bench'`

- [ ] **Step 3: Implement `bench/cli.py`**

```python
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bench.config import load_config
from bench.data import load_prices, update_prices
from bench.runner import run_estimator_day
from bench.store import Store
from estimators import registry


def _data():
    return Path(os.environ.get("BENCH_DATA", "data"))


def _assets_file():
    return os.environ.get("BENCH_ASSETS", "assets.yaml")


def _site():
    return Path(os.environ.get("BENCH_SITE", "site"))


def _run_date(arg, now):
    return arg or now.date().isoformat()


def cmd_list(args, now):
    print(json.dumps(registry.names()))
    return 0


def cmd_requirements(args, now):
    print(registry.REGISTRY[args.estimator].get("requirements", ""))
    return 0


def cmd_fetch(args, now):
    settings, assets = load_config(_assets_file())
    status = update_prices(_data() / "prices", assets, settings.history_start)
    for symbol, s in status.items():
        print(f"{symbol}: {s}")
    return 1 if all(s != "ok" for s in status.values()) else 0


def cmd_run(args, now):
    settings, assets = load_config(_assets_file())
    prices = load_prices(_data() / "prices", assets)
    estimator = registry.build(args.estimator)
    rec = run_estimator_day(
        Store(_data() / "live"), estimator, prices, _run_date(args.run_date, now), settings, now=now
    )
    print(json.dumps(rec))
    return 0 if rec["status"] in ("ok", "skipped_late") else 1


def cmd_backfill(args, now):
    settings, assets = load_config(_assets_file())
    prices = load_prices(_data() / "prices", assets)
    estimator = registry.build(args.estimator)
    store = Store(_data() / "backtest")
    end = date.fromisoformat(args.end) if args.end else now.date()
    days = [(end - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)]
    stride = max(1, estimator.backfill_stride)
    failed = 0
    for i, d in enumerate(days):
        if i % stride and i != len(days) - 1:
            continue
        rec = run_estimator_day(store, estimator, prices, d, settings)
        failed += rec["status"] == "failed"
        if i % 25 == 0:
            print(f"backfill {args.estimator}: {d} ({rec['status']})", file=sys.stderr)
    print(json.dumps({"estimator": args.estimator, "days": len(days), "failed_days": failed}))
    return 0


def cmd_aggregate(args, now):
    from bench.aggregate import build_all

    settings, assets = load_config(_assets_file())
    prices = load_prices(_data() / "prices", assets)
    build_all(
        _data(), _site() / "data", prices, settings, assets, _run_date(args.run_date, now),
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return 0


def cmd_notify(args, now):
    from bench.notify import notify

    return notify(
        _site() / "data" / "summary.json", _run_date(args.run_date, now), args.failure, os.environ
    )


def main(argv=None, now=None):
    now = now or datetime.now(timezone.utc)
    p = argparse.ArgumentParser(prog="bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("fetch")
    r = sub.add_parser("requirements")
    r.add_argument("--estimator", required=True)
    r = sub.add_parser("run")
    r.add_argument("--estimator", required=True)
    r.add_argument("--run-date")
    b = sub.add_parser("backfill")
    b.add_argument("--estimator", required=True)
    b.add_argument("--days", type=int, default=365)
    b.add_argument("--end")
    a = sub.add_parser("aggregate")
    a.add_argument("--run-date")
    n = sub.add_parser("notify")
    n.add_argument("--run-date")
    n.add_argument("--failure", action="store_true")
    args = p.parse_args(argv)
    commands = {
        "list": cmd_list, "requirements": cmd_requirements, "fetch": cmd_fetch, "run": cmd_run,
        "backfill": cmd_backfill, "aggregate": cmd_aggregate, "notify": cmd_notify,
    }
    return commands[args.cmd](args, now)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -v`
Expected: all pass. (`test_run_returns_nonzero...` monkeypatches `registry.build`; the CLI calls `registry.build` through the module, so the patch takes effect.)

- [ ] **Step 5: Commit**

```bash
git add bench/cli.py tests/test_cli.py
git commit -m "feat: command line for fetch, run, backfill, aggregate and notify"
```

---

### Task 8: Aggregate into dashboard JSON

**Files:**
- Create: `bench/aggregate.py`, `tests/test_aggregate.py`
- Test: `tests/test_aggregate.py`

**Interfaces:**
- Consumes: `Store`, `scoring`, `stale_assets`, `REGISTRY`, `Settings`, `Asset`, candle frames.
- Produces: `build_all(data_dir, out_dir, prices, settings, assets, run_date, generated_at=None)` writing `out_dir/summary.json` and `out_dir/estimators/<name>.json`. The dashboard reads exactly these shapes.

`summary.json`:

```
{ "schema_version": 1, "generated_at": "...Z", "run_date": "YYYY-MM-DD",
  "stale_assets": {"SOL-USD": 3, "XYZ": null},
  "estimators": [{"name","label","kind","source","license","original_code"}, ...],
  "modes": { "live": MODE, "backtest": MODE } }
MODE = { "dates": ["YYYY-MM-DD", ...],
         "rows":   {name: ROW}, "pnl": {name: [float|null per date]},
         "hit":    {name: [float|null per date]}, "equity": {name: [[date, equity], ...]},
         "hold":   [[date, equity], ...] }
ROW  = { "status": "ok|failed|skipped_late|no_run", "balance", "day_return", "day_change",
         "spark": [equity x <=30], "total_return", "max_drawdown", "worst_day",
         "hit_rate", "hit_rate_down", "n_days", "trades_per_day", "edge", "p_value",
         "too_early", "sanity" }
```

`estimators/<name>.json`: `{"schema_version", "name", "meta", "modes": {"live": D, "backtest": D}}` with `D = {"stats": ROW, "equity": [[date, equity]], "days": [{"date","equity","day_return","n_universe","n_traded","trades":[{"asset","asof","entry","exit","expected_return","traded","gross_ret","net_ret","actual_cc","hit"}]}], "per_asset": {asset: {"n","traded","hit_rate","net_return_sum"}}}`.

- [ ] **Step 1: Write the failing test**

`tests/test_aggregate.py`:

```python
import json

import pytest

from bench.aggregate import build_all
from bench.broker import settle_estimator
from bench.config import Asset, Settings
from bench.store import Store
from tests.helpers import candles

S = Settings()
ASSETS = [Asset("AAA", "stock", 5), Asset("BBB", "stock", 5)]


def prices():
    return {
        "AAA": candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)]),
        "BBB": candles([("2026-01-02", 50, 51, 49, 50), ("2026-01-05", 50, 51, 48, 49)]),
    }


def pred(asof, exp):
    return {"asof": asof, "expected_return": exp, "confidence": None, "path": None}


@pytest.fixture
def out(tmp_path):
    live = Store(tmp_path / "data" / "live")
    live.save_prediction("control_always_long", "2026-01-03", {"predictions": {
        "AAA": pred("2026-01-02", 1.0), "BBB": pred("2026-01-02", 1.0)}})
    live.save_prediction("control_random", "2026-01-03", {"predictions": {
        "AAA": pred("2026-01-02", 1.0), "BBB": pred("2026-01-02", -1.0)}})
    for n in ("control_always_long", "control_random"):
        settle_estimator(live, n, prices(), S)
        live.record_run(n, {"run_date": "2026-01-06", "estimator": n, "status": "ok"})
    live.record_run("analog", {"run_date": "2026-01-06", "estimator": "analog", "status": "failed", "error": "x"})
    target = tmp_path / "site" / "data"
    build_all(tmp_path / "data", target, prices(), S, ASSETS, "2026-01-06", generated_at="2026-01-06T00:41:00Z")
    return target


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_summary_shape_and_numbers(out):
    s = load(out / "summary.json")
    live = s["modes"]["live"]
    assert s["run_date"] == "2026-01-06" and s["stale_assets"] == {}
    assert live["dates"] == ["2026-01-05"]
    al, rnd = live["rows"]["control_always_long"], live["rows"]["control_random"]
    # always long: AAA +0.019, BBB -0.021 -> mean -0.001 ; random only trades AAA -> 0.0095
    assert al["balance"] == pytest.approx(9990.0) and al["day_return"] == pytest.approx(-0.001)
    assert rnd["balance"] == pytest.approx(10095.0) and live["pnl"]["control_random"] == [pytest.approx(0.0095)]
    assert al["hit_rate"] == 0.5 and rnd["hit_rate"] == 1.0 and rnd["hit_rate_down"] == 1.0
    assert al["hit_rate_down"] is None
    assert live["hit"]["control_random"] == [1.0] and live["equity"]["control_random"] == [["2026-01-05", 10095.0]]
    assert al["too_early"] is True and al["n_days"] == 1 and al["trades_per_day"] == 2.0


def test_hold_reference_line(out):
    live = load(out / "summary.json")["modes"]["live"]
    assert live["hold"] == [["2026-01-05", 10000.0]]  # +2% and -2% cancel


def test_failed_and_unrun_estimators(out):
    live = load(out / "summary.json")["modes"]["live"]
    assert live["rows"]["analog"]["status"] == "failed" and live["rows"]["analog"]["n_days"] == 0
    assert live["rows"]["xgb_indicators"]["status"] == "no_run"
    assert live["pnl"]["analog"] == [None]


def test_backtest_mode_is_empty_not_missing(out):
    bt = load(out / "summary.json")["modes"]["backtest"]
    assert bt["dates"] == [] and bt["rows"]["analog"]["n_days"] == 0


def test_estimator_detail_file(out):
    d = load(out / "estimators" / "control_random.json")["modes"]["live"]
    assert len(d["days"]) == 1 and len(d["days"][0]["trades"]) == 2
    assert d["per_asset"]["AAA"]["hit_rate"] == 1.0
    empty = load(out / "estimators" / "analog.json")["modes"]["live"]
    assert empty["days"] == [] and empty["per_asset"] == {}


def test_meta_has_no_internal_keys(out):
    meta = load(out / "summary.json")["estimators"][0]
    assert "target" not in meta and "requirements" not in meta and "label" in meta
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_aggregate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.aggregate'`

- [ ] **Step 3: Implement `bench/aggregate.py`**

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bench import scoring
from bench.data import stale_assets
from bench.store import SCHEMA_VERSION, Store
from estimators.registry import REGISTRY

CONTROL_RANDOM = "control_random"
PUBLIC_META_SKIP = ("target", "requirements")


def _records(df):
    return json.loads(df.to_json(orient="records"))


def _default(o):
    return o.item() if hasattr(o, "item") else str(o)


def _status_for(runs, run_date):
    todays = [r for r in runs if r.get("run_date") == run_date]
    return todays[-1]["status"] if todays else "no_run"


def _hold_curve(prices, dates, start_equity):
    """Equal-weight close-to-close buy and hold, no costs. A reference line, not an account."""
    per_date = {}
    for df in prices.values():
        d, c = df["date"].tolist(), df["close"].tolist()
        for i in range(1, len(d)):
            per_date.setdefault(d[i], []).append(c[i] / c[i - 1] - 1.0)
    eq, out = float(start_equity), []
    for day in dates:
        rets = per_date.get(day)
        if rets:
            eq *= 1.0 + sum(rets) / len(rets)
        out.append([day, round(eq, 2)])
    return out


def _row(eq, led, runs, settings, rand, run_date):
    n_days = len(eq)
    equities, rets = eq["equity"].tolist(), eq["day_return"].tolist()
    balance = equities[-1] if n_days else float(settings.start_equity)
    prev = equities[-2] if n_days > 1 else float(settings.start_equity)
    calls = led["hit"].dropna().tolist()
    down = led.loc[led["expected_return"] < 0, "hit"].dropna().tolist()
    edge = scoring.edge_vs_control(dict(zip(eq["date"], rets)), rand)
    return {
        "status": _status_for(runs, run_date),
        "balance": round(balance, 2),
        "day_return": rets[-1] if n_days else None,
        "day_change": round(balance - prev, 2) if n_days else 0.0,
        "spark": [round(e, 2) for e in equities[-30:]],
        "total_return": scoring.total_return(equities, settings.start_equity),
        "max_drawdown": scoring.max_drawdown(equities),
        "worst_day": scoring.worst_day(rets),
        "hit_rate": scoring.hit_rate(calls),
        "hit_rate_down": scoring.hit_rate(down),
        "n_days": n_days,
        "trades_per_day": float(eq["n_traded"].sum()) / n_days if n_days else 0.0,
        "edge": edge["edge"],
        "p_value": edge["p_value"],
        "too_early": n_days < settings.min_live_days,
        "sanity": scoring.sanity_flag(rets, settings.sanity_day_pct, settings.sanity_week_pct),
    }


def _detail(eq, led, row):
    trades_by_date = {d: g for d, g in led.groupby("settle_date")}
    days = []
    for rec in _records(eq):
        g = trades_by_date.get(rec["date"])
        trades = [] if g is None else _records(g.drop(columns=["settle_date"]))
        days.append({**rec, "trades": trades})
    per_asset = {}
    for asset, g in led.groupby("asset"):
        per_asset[asset] = {
            "n": int(len(g)), "traded": int(g["traded"].sum()),
            "hit_rate": scoring.hit_rate(g["hit"].dropna().tolist()),
            "net_return_sum": float(g["net_ret"].sum()),
        }
    equity = [[d, round(float(e), 2)] for d, e in zip(eq["date"], eq["equity"])]
    return {"stats": row, "equity": equity, "days": days, "per_asset": per_asset}


def _mode_block(data_dir, mode, prices, settings, run_date):
    store = Store(Path(data_dir) / mode)
    eqs = {n: store.load_equity(n) for n in REGISTRY}
    leds = {n: store.load_ledger(n) for n in REGISTRY}
    runs = {n: store.load_runs(n) for n in REGISTRY}
    dates = sorted({d for eq in eqs.values() for d in eq["date"]})
    rand = dict(zip(eqs[CONTROL_RANDOM]["date"], eqs[CONTROL_RANDOM]["day_return"]))
    rows, pnl, hit, equity = {}, {}, {}, {}
    for n in REGISTRY:
        rows[n] = _row(eqs[n], leds[n], runs[n], settings, rand, run_date)
        by_date = dict(zip(eqs[n]["date"], eqs[n]["day_return"]))
        pnl[n] = [by_date.get(d) for d in dates]
        scored = leds[n].dropna(subset=["hit"])
        hits = {} if scored.empty else scored.groupby("settle_date")["hit"].mean().to_dict()
        hit[n] = [hits.get(d) for d in dates]
        equity[n] = [[d, round(float(e), 2)] for d, e in zip(eqs[n]["date"], eqs[n]["equity"])]
    block = {
        "dates": dates, "rows": rows, "pnl": pnl, "hit": hit, "equity": equity,
        "hold": _hold_curve(prices, dates, settings.start_equity),
    }
    return block, eqs, leds


def build_all(data_dir, out_dir, prices, settings, assets, run_date, generated_at=None):
    out = Path(out_dir)
    (out / "estimators").mkdir(parents=True, exist_ok=True)
    meta = [
        {"name": n, **{k: v for k, v in m.items() if k not in PUBLIC_META_SKIP}}
        for n, m in REGISTRY.items()
    ]
    meta_by_name = {m["name"]: m for m in meta}
    details = {
        n: {"schema_version": SCHEMA_VERSION, "name": n, "meta": meta_by_name[n], "modes": {}}
        for n in REGISTRY
    }
    modes = {}
    for mode in ("live", "backtest"):
        block, eqs, leds = _mode_block(data_dir, mode, prices, settings, run_date)
        modes[mode] = block
        for n in REGISTRY:
            details[n]["modes"][mode] = _detail(eqs[n], leds[n], block["rows"][n])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_date": run_date,
        "stale_assets": stale_assets(prices, assets, run_date),
        "estimators": meta,
        "modes": modes,
    }
    (out / "summary.json").write_text(json.dumps(summary, default=_default), encoding="utf-8")
    for n, d in details.items():
        (out / "estimators" / f"{n}.json").write_text(json.dumps(d, default=_default), encoding="utf-8")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_aggregate.py -v`
Expected: 6 passed. If `test_summary_shape_and_numbers` fails on `hit_rate_down is None` for always-long: that is correct only because always-long never predicts down; if it fails some other way, print the row and fix the code, not the expectation.

- [ ] **Step 5: Commit**

```bash
git add bench/aggregate.py tests/test_aggregate.py
git commit -m "feat: aggregate store contents into dashboard JSON"
```

---

### Task 9: Local end to end on real data, with a data-integrity checker

This task proves the machinery on real prices before any cloud or UI work, and gives the dashboard tasks real data to render.

**Files:**
- Create: `scripts/verify_data.py`, `tests/test_verify_data.py`
- Test: `tests/test_verify_data.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `check(data_dir="data", assets_file="assets.yaml") -> list[str]` (empty list means clean). Invariants: every prediction's `asof` is strictly before its run date; each account's settled dates are unique and increasing; each account's equity equals `start * cumprod(1 + day_return)`; every ledger row's entry and exit equal the open and close of that asset's candle on that date. The script is run after every backfill, and again as a CI step in Task 13.

- [ ] **Step 1: Write the failing test**

`tests/test_verify_data.py`:

```python
import json
from pathlib import Path

import pandas as pd

from bench.broker import settle_estimator
from bench.config import Settings
from bench.store import Store
from scripts.verify_data import check
from tests.helpers import candles

ROOT = Path(__file__).resolve().parent.parent


def setup(tmp_path):
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    df = candles([("2026-01-02", 99, 101, 98, 100), ("2026-01-05", 100, 103, 99, 102)])
    df.to_csv(prices_dir / "SPY.csv", index=False)
    st = Store(tmp_path / "live")
    st.save_prediction("e", "2026-01-03", {"predictions": {
        "SPY": {"asof": "2026-01-02", "expected_return": 0.01, "confidence": None, "path": None}}})
    settle_estimator(st, "e", {"SPY": df}, Settings())
    return st


def test_clean_data_passes(tmp_path):
    setup(tmp_path)
    assert check(tmp_path, ROOT / "assets.yaml") == []


def test_look_ahead_is_caught(tmp_path):
    st = setup(tmp_path)
    f = st.est_dir("e") / "predictions" / "2026-01-03.json"
    payload = json.loads(f.read_text())
    payload["predictions"]["SPY"]["asof"] = "2026-01-03"
    f.write_text(json.dumps(payload))
    assert any("not before" in p for p in check(tmp_path, ROOT / "assets.yaml"))


def test_tampered_equity_is_caught(tmp_path):
    st = setup(tmp_path)
    p = st.est_dir("e") / "equity.csv"
    eq = pd.read_csv(p)
    eq.loc[0, "equity"] = 99999.0
    eq.to_csv(p, index=False)
    assert any("compound" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))


def test_ledger_price_mismatch_is_caught(tmp_path):
    st = setup(tmp_path)
    p = st.est_dir("e") / "ledger.csv"
    led = pd.read_csv(p)
    led.loc[0, "exit"] = 150.0
    led.to_csv(p, index=False)
    assert any("candle" in problem for problem in check(tmp_path, ROOT / "assets.yaml"))
```

Create empty `scripts/__init__.py` so `scripts.verify_data` imports.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_verify_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.verify_data'`

- [ ] **Step 3: Implement `scripts/verify_data.py`**

Note the tests pass a data directory laid out as `<dir>/prices` plus `<dir>/live` and `<dir>/backtest`.

```python
import sys
from pathlib import Path

from bench.config import load_config
from bench.data import load_prices
from bench.store import Store


def check(data_dir="data", assets_file="assets.yaml"):
    settings, assets = load_config(assets_file)
    prices = load_prices(Path(data_dir) / "prices", assets)
    problems = []
    for mode in ("live", "backtest"):
        root = Path(data_dir) / mode
        if not (root / "estimators").exists():
            continue
        store = Store(root)
        for name in sorted(p.name for p in (root / "estimators").iterdir() if p.is_dir()):
            where = f"{mode}/{name}"
            for run_date, payload in store.load_predictions(name).items():
                for asset, p in payload["predictions"].items():
                    if not p["asof"] < run_date:
                        problems.append(f"{where}/{run_date}/{asset}: asof {p['asof']} is not before the run date")
            eq = store.load_equity(name)
            if len(eq):
                if eq["date"].duplicated().any() or not eq["date"].is_monotonic_increasing:
                    problems.append(f"{where}: settled dates are not unique and increasing")
                expected = settings.start_equity * (1 + eq["day_return"]).cumprod()
                if (expected - eq["equity"]).abs().max() > 1e-6:
                    problems.append(f"{where}: equity does not compound from day returns")
            for r in store.load_ledger(name).itertuples():
                df = prices.get(r.asset)
                row = df[df["date"] == r.settle_date] if df is not None else []
                if len(row) != 1 or abs(row["open"].iloc[0] - r.entry) > 1e-9 or abs(row["close"].iloc[0] - r.exit) > 1e-9:
                    problems.append(f"{where}: ledger row {r.asset} {r.settle_date} does not match the candle")
                    break
    return problems


if __name__ == "__main__":
    found = check(sys.argv[1] if len(sys.argv) > 1 else "data")
    print("\n".join(found) if found else "data checks passed")
    sys.exit(1 if found else 0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_verify_data.py -v`
Expected: 4 passed

- [ ] **Step 5: Fetch real prices**

Run: `python -m bench.cli fetch`
Expected: 21 lines `SYMBOL: ok`. Any `error:` line is a data-source problem: retry once; if an asset keeps failing, note it in `docs/data-sources.md` and continue (a stale asset is a supported state).

- [ ] **Step 6: Backfill the cheap estimators locally**

```bash
for e in control_always_long control_random control_persistence analog candle_rules; do
  python -m bench.cli backfill --estimator "$e" --days 365
done
python -m bench.cli backfill --estimator xgb_indicators --days 365
```

Expected: each prints a JSON line with `"failed_days": 0`. XGBoost retrains every day, so expect it to take roughly 10 to 30 minutes; run it in the background and continue once it finishes. If any estimator reports failed days, read the error in `data/backtest/estimators/<name>/runs.jsonl`, fix the cause, delete `data/backtest/estimators/<name>`, and re-run it.

- [ ] **Step 7: Verify data integrity**

Run: `python scripts/verify_data.py data`
Expected: `data checks passed`. A failure here is a real bug in the broker, runner or store: do not proceed until it is fixed.

- [ ] **Step 8: Sanity-read the numbers**

```bash
python -m bench.cli aggregate
python - <<'EOF'
import json
s = json.load(open("site/data/summary.json"))
bt = s["modes"]["backtest"]
print("backtest days:", len(bt["dates"]), bt["dates"][0], "->", bt["dates"][-1])
for n, r in bt["rows"].items():
    print(f"{n:22s} balance {r['balance']:>10.2f}  hit {r['hit_rate']}  trades/day {r['trades_per_day']:.1f}  p {r['p_value']:.3f}")
print("hold reference ends at", bt["hold"][-1])
EOF
```

Read the output honestly, and report it to the owner as it is:
- A control or estimator that gained more than about 50% in a year is suspect (look for a leak) before it is exciting.
- `control_always_long` should land near, but not at, the hold line. It misses overnight gains and pays costs.
- An estimator with `trades/day` near 0 is simply cash; say so.
- `hit_rate` for `control_random` should be close to 0.5. If it is far from 0.5, there is a bug.

- [ ] **Step 9: Commit the data**

```bash
git add scripts tests data
git commit -m "feat: data integrity checker and a real one-year backtest for the first estimators"
```

---

### Task 10: Dashboard shell and overview

**Rulebook:** read ch 8 (`02-book/2-the-look-and-feel/08-colour-contrast-and-theming.md`), ch 28 (`02-book/5-the-qualities/28-accessibility.md`), ch 23 (`02-book/4-the-states-nobody-asks-for/23-empty-loading-partial-offline.md`), ch 25 (`02-book/4-the-states-nobody-asks-for/25-edge-cases.md`) and ch 17 (`02-book/3-the-build/17-interaction-states.md`). Where a chapter conflicts with a step below, the chapter wins; record the change in the commit message.

**Files:**
- Create: `site/index.html`, `site/style.css`, `site/lib.js`, `site/lib.test.js`, `site/charts.js`, `site/app.js`, `.claude/launch.json`
- Test: `site/lib.test.js` (run with `node --test site/`)

**Interfaces:**
- Consumes: `site/data/summary.json` and `site/data/estimators/<name>.json` from Task 8 (shapes documented there).
- Produces (`lib.js`, pure, tested): `PALETTES`, `cellColor(value, scale, palette)`, `signMark(v)`, `fmtPct(v, digits=2)`, `fmtUsd(v)`, `calendarCells(dates) -> [{date, col, row}]`, `luckText(row)`. (`charts.js`): `sparkline(values)`, `lineChart(container, series, opts)` with `series = [{name, color, dashed, points: [[date, value]]}]`.

- [ ] **Step 1: Check Node**

Run: `node --version`
Expected: v18 or newer. If missing, ask the owner before installing (`winget install OpenJS.NodeJS.LTS`).

- [ ] **Step 2: Write the failing library tests**

First create `site/package.json` (so Node treats the `.js` files as ES modules):

```json
{ "private": true, "type": "module" }
```

Then `site/lib.test.js`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { cellColor, signMark, fmtPct, fmtUsd, calendarCells, luckText } from "./lib.js";

test("fmtPct keeps the sign and handles missing values", () => {
  assert.equal(fmtPct(0.0123), "+1.23%");
  assert.equal(fmtPct(-0.005), "-0.50%");
  assert.equal(fmtPct(0), "0.00%");
  assert.equal(fmtPct(null), "n/a");
});

test("fmtUsd", () => {
  assert.equal(fmtUsd(10190), "$10,190.00");
  assert.equal(fmtUsd(null), "n/a");
});

test("signMark gives a non-colour signal", () => {
  assert.equal(signMark(0.01), "▲");
  assert.equal(signMark(-0.01), "▼");
  assert.equal(signMark(0), "•");
});

test("cellColor scales alpha with magnitude and clamps", () => {
  assert.equal(cellColor(0.02, 0.02), "rgba(63,185,80,1.00)");
  assert.equal(cellColor(0.5, 0.02), "rgba(63,185,80,1.00)");
  assert.equal(cellColor(-0.01, 0.02), "rgba(248,81,73,0.60)");
  assert.equal(cellColor(0.01, 0.02, "cvd"), "rgba(88,166,255,0.60)");
  assert.equal(cellColor(-0.02, 0.02, "cvd"), "rgba(240,136,62,1.00)");
});

test("cellColor handles empty cells", () => {
  assert.equal(cellColor(null, 0.02), "var(--cell-empty)");
  assert.equal(cellColor(undefined, 0.02), "var(--cell-empty)");
  assert.equal(cellColor(NaN, 0.02), "var(--cell-empty)");
});

test("calendarCells fills the gaps and starts on the right weekday", () => {
  // 2026-01-05 is a Monday, so row 1 (Sunday is row 0).
  const cells = calendarCells(["2026-01-05", "2026-01-07"]);
  assert.deepEqual(cells.map((c) => c.date), ["2026-01-05", "2026-01-06", "2026-01-07"]);
  assert.equal(cells[0].row, 1);
  assert.equal(cells[0].col, 0);
  assert.equal(cells[2].row, 3);
});

test("calendarCells rolls into the next week", () => {
  const cells = calendarCells(["2026-01-09", "2026-01-12"]); // Friday to Monday
  assert.equal(cells[0].col, 0);
  assert.equal(cells.at(-1).col, 1);
  assert.equal(cells.at(-1).row, 1);
});

test("calendarCells with one date and none", () => {
  assert.equal(calendarCells(["2026-01-05"]).length, 1);
  assert.deepEqual(calendarCells([]), []);
});

test("luckText never overclaims", () => {
  assert.equal(luckText({ n_days: 0 }), "no data");
  assert.equal(luckText({ n_days: 10, too_early: true, p_value: 0.001 }), "too early to tell");
  assert.match(luckText({ n_days: 90, too_early: false, p_value: 0.01 }), /^unlikely luck/);
  assert.match(luckText({ n_days: 90, too_early: false, p_value: 0.4 }), /^consistent with luck/);
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `node --test site/`
Expected: FAIL with `Cannot find module` for `./lib.js`

- [ ] **Step 4: Implement `site/lib.js`**

```js
export const PALETTES = {
  default: { pos: [63, 185, 80], neg: [248, 81, 73] },
  cvd: { pos: [88, 166, 255], neg: [240, 136, 62] },
};

export function cellColor(value, scale, palette = "default") {
  if (value === null || value === undefined || Number.isNaN(value)) return "var(--cell-empty)";
  const [r, g, b] = value >= 0 ? PALETTES[palette].pos : PALETTES[palette].neg;
  const alpha = 0.2 + 0.8 * Math.min(Math.abs(value) / scale, 1);
  return `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
}

export function signMark(v) {
  return v > 0 ? "▲" : v < 0 ? "▼" : "•";
}

export function fmtPct(v, digits = 2) {
  if (v === null || v === undefined) return "n/a";
  return (v > 0 ? "+" : "") + (v * 100).toFixed(digits) + "%";
}

export function fmtUsd(v) {
  if (v === null || v === undefined) return "n/a";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const toDay = (s) => Math.floor(Date.parse(s + "T00:00:00Z") / 86400000);

export function calendarCells(dates) {
  if (!dates.length) return [];
  const first = toDay(dates[0]);
  const last = toDay(dates[dates.length - 1]);
  const offset = new Date(first * 86400000).getUTCDay(); // 0 = Sunday
  const cells = [];
  for (let d = first; d <= last; d++) {
    const idx = d - first + offset;
    cells.push({
      date: new Date(d * 86400000).toISOString().slice(0, 10),
      col: Math.floor(idx / 7),
      row: idx % 7,
    });
  }
  return cells;
}

export function luckText(row) {
  if (!row.n_days) return "no data";
  if (row.too_early) return "too early to tell";
  return row.p_value < 0.05
    ? `unlikely luck (p=${row.p_value.toFixed(3)})`
    : `consistent with luck (p=${row.p_value.toFixed(2)})`;
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `node --test site/`
Expected: all tests pass.

- [ ] **Step 6: Write `site/index.html` and `site/style.css`**

`site/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Prediction bench</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>prediction bench</h1>
  <div class="controls">
    <span role="group" aria-label="Data set">
      <button type="button" data-mode="live">Live</button>
      <button type="button" data-mode="backtest">Backtest</button>
    </span>
    <button type="button" id="palette" aria-pressed="false">Colour-blind palette</button>
  </div>
</header>
<nav id="tabs" aria-label="Estimators"></nav>
<main id="view" tabindex="-1"><p class="dim">Loading…</p></main>
<footer>
  Paper trading experiment on public price data. Not investment advice.
  Each prediction is committed before the session it trades; a crypto trade enters at the
  00:00 UTC open and its prediction is committed up to 12 hours later.
</footer>
<script type="module" src="app.js"></script>
</body>
</html>
```

`site/style.css`:

```css
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#c9d1d9;--dim:#8b949e;--amber:#d29922;--pos:#3fb950;--neg:#f85149;--cell-empty:#1c2128;--font:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
:root[data-palette="cvd"]{--pos:#58a6ff;--neg:#f0883e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 var(--font)}
header,nav,main,footer{max-width:1200px;margin:0 auto;padding-left:16px;padding-right:16px}
header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding-top:16px;padding-bottom:8px}
h1{font-size:16px;margin:0;color:var(--amber);letter-spacing:.04em;font-weight:600}
h2{font-size:13px;margin:24px 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em;font-weight:600}
h3{font-size:14px;margin:0 0 4px}
button{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--line);padding:4px 10px;border-radius:4px;cursor:pointer}
button[aria-pressed="true"]{border-color:var(--amber);color:var(--amber)}
button:focus-visible,a:focus-visible,summary:focus-visible,main:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
nav{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line)}
nav a{color:var(--dim);text-decoration:none;padding:6px 10px;white-space:nowrap;border-bottom:2px solid transparent}
nav a[aria-current="page"]{color:var(--text);border-bottom-color:var(--amber)}
.strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px}
.tile{display:block;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px;color:inherit;text-decoration:none}
.tile:hover{border-color:var(--dim)}
.tile-name{color:var(--dim);font-size:12px}
.tile-bal{font-size:18px;margin:2px 0}
.up{color:var(--pos)}.down{color:var(--neg)}.flat{color:var(--dim)}
.badge{display:inline-block;font-size:11px;padding:0 6px;border:1px solid var(--amber);color:var(--amber);border-radius:3px;margin-right:4px}
.badge.bad{border-color:var(--neg);color:var(--neg)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--dim);font-weight:400}
.tablewrap,.heat{overflow-x:auto}
.heat-row{display:flex;align-items:center;gap:8px;margin:2px 0}
.heat-label{flex:0 0 190px;color:var(--dim);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.heat-cells{display:flex;gap:2px}
.cell{width:11px;height:11px;border-radius:2px;flex:0 0 auto}
.cal{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,11px);grid-auto-columns:11px;gap:2px;overflow-x:auto;padding-bottom:4px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px;margin:16px 0}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--dim);margin-top:4px}
.legend i{display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle}
.warn{color:var(--amber)}.dim{color:var(--dim)}.note{color:var(--dim);font-size:12px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.stat b{display:block;font-size:16px;font-weight:400}
details.day{border-bottom:1px solid var(--line);padding:4px 0}
details.day summary{cursor:pointer;display:flex;gap:16px;flex-wrap:wrap}
footer{color:var(--dim);font-size:12px;padding-top:24px;padding-bottom:32px}
svg.chart text{fill:var(--dim);font-size:10px;font-family:var(--font)}
@media (prefers-reduced-motion:no-preference){.tile{transition:border-color .15s}}
@media (max-width:600px){.heat-label{flex-basis:110px}}
```

- [ ] **Step 7: Write `site/charts.js`**

```js
const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
  return n;
};
const day = (s) => Date.parse(s + "T00:00:00Z") / 86400000;

export function sparkline(values, { width = 120, height = 28 } = {}) {
  if (!values || values.length < 2) return document.createElement("span");
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const s = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, "aria-hidden": "true" });
  s.append(svg("polyline", { points: pts, fill: "none", stroke: "currentColor", "stroke-width": "1.5" }));
  return s;
}

function note(text) {
  const p = document.createElement("p");
  p.className = "note";
  p.textContent = text;
  return p;
}

export function lineChart(container, series, { height = 240, label = "Account value over time" } = {}) {
  container.textContent = "";
  const usable = series.filter((s) => s.points.length > 0);
  const all = usable.flatMap((s) => s.points);
  const xs = all.map((p) => day(p[0]));
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  if (all.length < 2 || x1 === x0) {
    container.append(note("Not enough days to draw a chart yet."));
    return;
  }
  const W = 800, padL = 56, padR = 8, padT = 8, padB = 20;
  const ys = all.map((p) => p[1]);
  let y0 = Math.min(...ys);
  let y1 = Math.max(...ys);
  if (y1 === y0) { y0 -= 1; y1 += 1; }
  const sx = (d) => padL + ((day(d) - x0) / (x1 - x0)) * (W - padL - padR);
  const sy = (v) => padT + (1 - (v - y0) / (y1 - y0)) * (height - padT - padB);
  const s = svg("svg", { viewBox: `0 0 ${W} ${height}`, class: "chart", role: "img", "aria-label": label, width: "100%" });
  for (const v of [y0, (y0 + y1) / 2, y1]) {
    s.append(svg("line", { x1: padL, x2: W - padR, y1: sy(v), y2: sy(v), stroke: "#30363d", "stroke-width": "1" }));
    const t = svg("text", { x: padL - 6, y: sy(v) + 3, "text-anchor": "end" });
    t.textContent = "$" + Math.round(v).toLocaleString("en-US");
    s.append(t);
  }
  const dates = all.map((p) => p[0]).sort();
  const left = svg("text", { x: padL, y: height - 4 });
  left.textContent = dates[0];
  const right = svg("text", { x: W - padR, y: height - 4, "text-anchor": "end" });
  right.textContent = dates[dates.length - 1];
  s.append(left, right);
  for (const ser of usable) {
    const pts = ser.points.map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
    s.append(svg("polyline", {
      points: pts, fill: "none", stroke: ser.color,
      "stroke-width": ser.dashed ? "1" : "1.6", "stroke-dasharray": ser.dashed ? "4 3" : undefined,
    }));
  }
  container.append(s);
  const legend = document.createElement("div");
  legend.className = "legend";
  for (const ser of usable) {
    const item = document.createElement("span");
    const sw = document.createElement("i");
    sw.style.background = ser.color;
    item.append(sw, ser.name);
    legend.append(item);
  }
  container.append(legend);
}
```

- [ ] **Step 8: Write `site/app.js` (shell, overview and estimator route stub)**

```js
import { cellColor, signMark, fmtPct, fmtUsd, calendarCells, luckText } from "./lib.js";
import { lineChart, sparkline } from "./charts.js";

const COLORS = ["#58a6ff", "#d29922", "#3fb950", "#bc8cff", "#f778ba", "#39c5cf", "#ff7b72", "#ffa657", "#7ee787", "#a5d6ff"];
const CONTROL_COLOR = "#6e7681";
const PNL_SCALE = 0.02;
const HIT_SCALE = 0.5;
const HEAT_DAYS = 90;

const store = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable: fine */ } };

const state = { mode: store("mode", "live"), palette: store("palette", "default"), summary: null, detail: {} };

export function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  n.append(...kids.filter((x) => x !== null && x !== undefined));
  return n;
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

const meta = () => Object.fromEntries(state.summary.estimators.map((e) => [e.name, e]));
const block = () => state.summary.modes[state.mode];

function colorMap() {
  const out = {};
  let i = 0;
  for (const e of state.summary.estimators) out[e.name] = e.kind === "control" ? CONTROL_COLOR : COLORS[i++ % COLORS.length];
  return out;
}

function trend(v) { return v > 0 ? "up" : v < 0 ? "down" : "flat"; }

function badges(r) {
  const out = [];
  if (r.status !== "ok" && r.status !== "no_run") out.push(el("span", { class: "badge bad" }, r.status.replace("_", " ")));
  if (r.sanity) out.push(el("span", { class: "badge" }, "check this"));
  return out;
}

function panel(title, text) {
  return el("div", { class: "panel" }, el("h3", {}, title), el("p", { class: "dim" }, text));
}

function showError(message, retry) {
  const view = document.getElementById("view");
  view.textContent = "";
  view.append(el("div", { class: "panel" }, el("p", { class: "warn" }, message), el("button", { type: "button", onclick: retry }, "Retry")));
}

function heatGrid(b, names, key, scale) {
  const m = meta();
  const dates = b.dates.slice(-HEAT_DAYS);
  const offset = b.dates.length - dates.length;
  const label = key === "hit" ? "Heatmap of direction hit rate per day" : "Heatmap of daily account return";
  const wrap = el("div", { class: "heat", role: "img", "aria-label": `${label}. The same numbers are in the leaderboard and on each estimator's tab.` });
  for (const n of names) {
    const cells = el("div", { class: "heat-cells" });
    dates.forEach((d, i) => {
      const v = b[key][n][offset + i];
      const dev = key === "hit" && v !== null ? v - 0.5 : v;
      const text = v === null ? `${d}: no calls` : key === "hit" ? `${d}: ${signMark(dev)} ${(v * 100).toFixed(0)}% correct` : `${d}: ${signMark(v)} ${fmtPct(v)}`;
      cells.append(el("div", { class: "cell", title: text, style: `background:${cellColor(dev, scale, state.palette)}` }));
    });
    wrap.append(el("div", { class: "heat-row" }, el("span", { class: "heat-label" }, m[n].label), cells));
  }
  return wrap;
}

function renderOverview(view) {
  const m = meta();
  const colors = colorMap();
  const b = block();
  const names = state.summary.estimators.map((e) => e.name);
  const active = names.filter((n) => b.rows[n].n_days > 0);
  const stale = Object.entries(state.summary.stale_assets);

  if (state.mode === "backtest") {
    view.append(el("p", { class: "note" }, "Backtest: every day replayed using only earlier data. Pretrained models may have seen this period in training, so their backtest numbers may be optimistic. Live results are the real verdict."));
  }
  if (stale.length) {
    view.append(el("p", { class: "warn" }, "Stale data: " + stale.map(([s, g]) => (g === null ? `${s} (no data)` : `${s} (${g} days behind)`)).join(", ")));
  }
  if (!active.length) {
    view.append(panel(
      state.mode === "live" ? "No settled days yet" : "No backtest data yet",
      state.mode === "live"
        ? "Predictions are being logged. The first results appear after the next trading session closes."
        : "Run the backfill workflow to fill in the past year."
    ));
    return;
  }

  view.append(el("h2", {}, "Wallets"));
  const strip = el("div", { class: "strip" });
  for (const n of [...active].sort((a, c) => b.rows[c].balance - b.rows[a].balance)) {
    const r = b.rows[n];
    strip.append(el("a", { class: "tile", href: `#/e/${n}`, style: `color:${colors[n]}` },
      el("div", { class: "tile-name" }, m[n].label),
      el("div", { class: "tile-bal", style: "color:var(--text)" }, fmtUsd(r.balance)),
      el("div", { class: trend(r.day_return) }, `${signMark(r.day_return)} ${fmtPct(r.day_return)}  (${r.day_change >= 0 ? "+" : "-"}${fmtUsd(Math.abs(r.day_change))})`),
      sparkline(r.spark),
      el("div", {}, ...badges(r))));
  }
  view.append(strip);

  view.append(el("h2", {}, "Account value"));
  const chart = el("div", {});
  view.append(chart);
  const series = active.map((n) => ({ name: m[n].label, color: colors[n], dashed: m[n].kind === "control", points: b.equity[n] }));
  series.push({ name: "Buy and hold (reference, no costs)", color: "#8b949e", dashed: true, points: b.hold });
  lineChart(chart, series);

  view.append(el("h2", {}, "Leaderboard"));
  const head = ["Estimator", "Balance", "Return", "Edge vs random", "Hit", "Down calls hit", "Max drawdown", "Worst day", "Trades/day", "Luck check", "Status"];
  const rows = names.map((n) => {
    const r = b.rows[n];
    const hit = (v) => (v === null ? "n/a" : (v * 100).toFixed(1) + "%");
    return el("tr", {},
      el("td", {}, el("a", { href: `#/e/${n}`, style: "color:inherit" }, m[n].label)),
      el("td", {}, fmtUsd(r.balance)),
      el("td", { class: trend(r.total_return) }, `${signMark(r.total_return)} ${fmtPct(r.total_return)}`),
      el("td", {}, m[n].kind === "control" ? "baseline" : fmtPct(r.edge, 3)),
      el("td", {}, hit(r.hit_rate)), el("td", {}, hit(r.hit_rate_down)),
      el("td", {}, fmtPct(r.max_drawdown)), el("td", {}, fmtPct(r.worst_day)),
      el("td", {}, r.trades_per_day.toFixed(1)),
      el("td", {}, m[n].kind === "control" ? "baseline" : luckText(r)),
      el("td", {}, ...badges(r), r.status === "ok" ? "ok" : r.status === "no_run" ? "not run yet" : ""));
  });
  view.append(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...head.map((h) => el("th", {}, h)))), el("tbody", {}, ...rows))));
  view.append(el("p", { class: "note" }, "Edge is the average daily return minus the random control's. Trades/day near 0 means the estimator mostly stayed in cash."));

  view.append(el("h2", {}, "Daily account return (last 90 days)"));
  view.append(heatGrid(b, active, "pnl", PNL_SCALE));
  view.append(el("h2", {}, "Direction hit rate per day (last 90 days)"));
  view.append(heatGrid(b, active, "hit", HIT_SCALE));
  view.append(el("p", { class: "note" }, "Brighter means bigger. For hit rate, bright green is mostly right, bright red mostly wrong, and dim is about 50%."));
}

function renderTabs(route) {
  const tabs = document.getElementById("tabs");
  tabs.textContent = "";
  const link = (href, text, current) => el("a", { href, "aria-current": current ? "page" : undefined }, text);
  tabs.append(link("#/", "Overview", !route.startsWith("e/")));
  for (const e of state.summary.estimators) tabs.append(link(`#/e/${e.name}`, e.label, route === `e/${e.name}`));
}

export function render() {
  const route = location.hash.replace(/^#\/?/, "");
  const view = document.getElementById("view");
  view.textContent = "";
  document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)));
  if (!state.summary) return;
  renderTabs(route);
  if (route.startsWith("e/")) return renderEstimator(view, decodeURIComponent(route.slice(2)));
  renderOverview(view);
}

// Replaced in Task 11.
function renderEstimator(view, name) {
  view.append(panel(name, "This tab is built in the next task."));
}

function applyPalette() {
  document.documentElement.dataset.palette = state.palette;
  document.getElementById("palette").setAttribute("aria-pressed", String(state.palette === "cvd"));
}

async function boot() {
  applyPalette();
  try {
    state.summary = await getJSON("data/summary.json");
  } catch {
    return showError("Couldn't load the data. Check your connection, then retry.", boot);
  }
  render();
}

document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
  state.mode = b.dataset.mode; keep("mode", state.mode); render();
}));
document.getElementById("palette").addEventListener("click", () => {
  state.palette = state.palette === "cvd" ? "default" : "cvd"; keep("palette", state.palette); applyPalette(); render();
});
window.addEventListener("hashchange", () => { render(); document.getElementById("view").focus(); });
boot();
```

- [ ] **Step 9: Serve and look at it with real data**

Create `.claude/launch.json`:

```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "site", "runtimeExecutable": "python", "runtimeArgs": ["-m", "http.server", "8000", "-d", "site"], "port": 8000 }
  ]
}
```

Run `python -m bench.cli aggregate` (so `site/data` is fresh), then `preview_start` with name `site` and open `http://localhost:8000`. Check, using `read_console_messages` (expect no errors) and screenshots:
1. **Backtest view:** wallet tiles, the account value chart, leaderboard, both heatmaps render with the 6 estimators.
2. **Live view** (the default): shows the "No settled days yet" panel, not a blank page.
3. **Colour-blind palette** switch turns green/red into blue/orange in heatmaps, tile deltas and text.
4. **Mobile width** (`resize_window` preset `mobile`): no horizontal page scroll (tables and heatmaps scroll inside their own boxes); reset with preset `desktop`.
5. Tab key reaches the controls, tabs and tiles in a sensible order with a visible focus outline.

Fix any defect found before moving on. The empty live state is the Review Focus item 5; also confirm a chart with a single date (set `b.dates` to one entry in the browser console) shows "Not enough days to draw a chart yet." instead of an error.

- [ ] **Step 10: Commit**

```bash
git add site .claude/launch.json
git commit -m "feat: terminal-style dashboard overview with wallets, leaderboard and two heatmaps"
```

---

### Task 11: Per-estimator tab

**Files:**
- Modify: `site/app.js` (replace the `renderEstimator` stub and add `calendar`, `statsPanel`, `dayList`, `assetTable`)
- Test: manual in the browser, plus the existing `node --test site/`

**Interfaces:**
- Consumes: `data/estimators/<name>.json` (Task 8 shape), `calendarCells`, `lineChart`, helpers already in `app.js`.
- Produces: route `#/e/<name>` showing, for the selected mode (Live or Backtest): header (what it is, source, licence, original code or reimplementation), stats, equity chart against the random control and the hold line, two GitHub-style calendars (daily return, hit rate), per-asset table, and a day-by-day list that expands to every asset's predicted vs actual.

- [ ] **Step 1: Replace the stub in `site/app.js`**

Delete the "Replaced in Task 11" `renderEstimator` function and add this code in its place:

```js
function calendar(days, valueOf, scale, kind) {
  const byDate = Object.fromEntries(days.map((d) => [d.date, valueOf(d)]));
  const cells = calendarCells(days.map((d) => d.date));
  const grid = el("div", { class: "cal", role: "img", "aria-label": `Calendar heatmap of ${kind}. The day list below has the same numbers.` });
  cells.forEach((c, i) => {
    const v = byDate[c.date] ?? null;
    const dev = kind === "hit rate" && v !== null ? v - 0.5 : v;
    const text = v === null ? `${c.date}: no session or no calls` : kind === "hit rate" ? `${c.date}: ${signMark(dev)} ${(v * 100).toFixed(0)}% correct` : `${c.date}: ${signMark(v)} ${fmtPct(v)}`;
    grid.append(el("div", { class: "cell", title: text, style: `background:${cellColor(dev, scale, state.palette)};${i === 0 ? `grid-row:${c.row + 1};` : ""}` }));
  });
  return grid;
}

function dayHit(d) {
  const hits = d.trades.map((t) => t.hit).filter((h) => h !== null && h !== undefined);
  return hits.length ? hits.reduce((a, b) => a + b, 0) / hits.length : null;
}

function statsPanel(s, kind) {
  const hit = (v) => (v === null ? "n/a" : (v * 100).toFixed(1) + "%");
  const items = [
    ["Balance", fmtUsd(s.balance)], ["Return", `${signMark(s.total_return)} ${fmtPct(s.total_return)}`],
    ["Days settled", String(s.n_days)], ["Hit rate", hit(s.hit_rate)], ["Down calls hit", hit(s.hit_rate_down)],
    ["Max drawdown", fmtPct(s.max_drawdown)], ["Worst day", fmtPct(s.worst_day)], ["Trades per day", s.trades_per_day.toFixed(1)],
    ["Luck check", kind === "control" ? "baseline" : luckText(s)],
  ];
  return el("div", { class: "stats" }, ...items.map(([k, v]) => el("div", { class: "stat" }, el("span", { class: "dim" }, k), el("b", {}, v))));
}

function assetTable(perAsset) {
  const rows = Object.entries(perAsset).sort((a, b) => b[1].net_return_sum - a[1].net_return_sum);
  const hit = (v) => (v === null ? "n/a" : (v * 100).toFixed(1) + "%");
  return el("div", { class: "tablewrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ...["Asset", "Calls", "Traded", "Hit", "Sum of trade returns"].map((h) => el("th", {}, h)))),
    el("tbody", {}, ...rows.map(([a, p]) => el("tr", {}, el("td", {}, a), el("td", {}, String(p.n)), el("td", {}, String(p.traded)), el("td", {}, hit(p.hit_rate)), el("td", { class: trend(p.net_return_sum) }, `${signMark(p.net_return_sum)} ${fmtPct(p.net_return_sum)}`))))));
}

function dayList(days, isControl) {
  const wrap = el("div", {});
  const draw = (limit) => {
    wrap.textContent = "";
    for (const d of [...days].reverse().slice(0, limit)) {
      const trades = el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Asset", "Predicted", "Actual", "Hit", "Traded", "Net return"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...d.trades.map((t) => el("tr", {},
          el("td", {}, t.asset),
          el("td", {}, isControl ? (t.expected_return > 0 ? "▲ long" : "▼ down") : `${signMark(t.expected_return)} ${fmtPct(t.expected_return)}`),
          el("td", {}, `${signMark(t.actual_cc)} ${fmtPct(t.actual_cc)}`),
          el("td", {}, t.hit === null || t.hit === undefined ? "n/a" : t.hit ? "yes" : "no"),
          el("td", {}, t.traded ? "yes" : "no (cash)"),
          el("td", { class: trend(t.net_ret) }, `${signMark(t.net_ret)} ${fmtPct(t.net_ret)}`))))));
      wrap.append(el("details", { class: "day" },
        el("summary", {}, el("span", {}, d.date), el("span", { class: trend(d.day_return) }, `${signMark(d.day_return)} ${fmtPct(d.day_return)}`), el("span", { class: "dim" }, `${fmtUsd(d.equity)} · ${d.n_traded} of ${d.n_universe} traded`)),
        trades));
    }
    if (days.length > limit) wrap.append(el("button", { type: "button", onclick: () => draw(days.length) }, `Show all ${days.length} days`));
  };
  draw(30);
  return wrap;
}

async function renderEstimator(view, name) {
  const startHash = location.hash;
  const m = meta()[name];
  if (!m) { view.append(panel("Unknown estimator", `There is no estimator called ${name}.`)); return; }
  view.append(el("p", { class: "dim" }, "Loading…"));
  let d = state.detail[name];
  if (!d) {
    try {
      d = state.detail[name] = await getJSON(`data/estimators/${name}.json`);
    } catch {
      if (location.hash !== startHash) return;
      return showError(`Couldn't load ${m.label}. Check your connection, then retry.`, render);
    }
  }
  if (location.hash !== startHash) return; // the user already moved on
  view.textContent = "";
  const mode = d.modes[state.mode];
  const isControl = m.kind === "control";
  view.append(el("h2", {}, m.label));
  view.append(el("p", { class: "dim" }, `${m.kind} · ${m.source} · licence: ${m.license} · ${m.original_code ? "original code" : "our own implementation"}`));
  if (state.mode === "backtest") view.append(el("p", { class: "note" }, "Backtest: each day replayed using only earlier data. Pretrained models may have seen this period in training, so their backtest numbers may be optimistic."));
  if (!mode.days.length) {
    view.append(panel(state.mode === "live" ? "No settled days yet" : "No backtest data yet", state.mode === "live" ? "Its predictions are being logged. Results appear after the next trading session closes." : "Run the backfill workflow to fill in the past year."));
    return;
  }
  view.append(el("h2", {}, "Summary"), statsPanel(mode.stats, m.kind));
  if (mode.stats.sanity) view.append(el("p", { class: "warn" }, "check this: a gain this large is more likely a bug or a data leak than skill."));

  view.append(el("h2", {}, "Account value"));
  const chart = el("div", {});
  view.append(chart);
  const b = block();
  const series = [{ name: m.label, color: "#58a6ff", dashed: false, points: mode.equity }];
  if (name !== "control_random") series.push({ name: "Random coin (control)", color: CONTROL_COLOR, dashed: true, points: b.equity.control_random });
  series.push({ name: "Buy and hold (reference, no costs)", color: "#8b949e", dashed: true, points: b.hold });
  lineChart(chart, series);

  view.append(el("h2", {}, "Daily account return"), calendar(mode.days, (x) => x.day_return, PNL_SCALE, "daily return"));
  view.append(el("h2", {}, "Direction hit rate"), calendar(mode.days, dayHit, HIT_SCALE, "hit rate"));
  view.append(el("p", { class: "note" }, "Each square is one calendar day, oldest at the left. Empty squares are days with no session or no calls."));
  view.append(el("h2", {}, "By asset"), assetTable(mode.per_asset));
  view.append(el("h2", {}, "Day by day"), dayList(mode.days, isControl));
}
```

- [ ] **Step 2: Verify in the browser**

With the preview running, open `#/e/xgb_indicators`, `#/e/control_random` and `#/e/analog` and check, via screenshots and `read_console_messages` (no errors):
1. Header text, stats, equity chart, both calendars, per-asset table, day list render in Backtest mode.
2. A day row expands to a per-asset table with predicted, actual, hit, traded and net return, with ▲/▼ markers.
3. The first calendar column starts on the correct weekday (compare a date you know: 2026-01-05 is a Monday).
4. Live mode shows the "No settled days yet" panel for every estimator.
5. Switching tabs quickly (click two estimators in a row) never leaves the first one's content on the second one's tab.
6. An unknown route (`#/e/nope`) shows the "Unknown estimator" panel.

- [ ] **Step 3: Run the JS tests again and commit**

Run: `node --test site/` (expected: all pass).

```bash
git add site/app.js
git commit -m "feat: per-estimator tab with calendars, per-asset breakdown and day-by-day detail"
```

---

### Task 12: Phone notification

**Rulebook:** read ch 30 (`02-book/5-the-qualities/30-security-and-secrets.md`): the topic is a credential and must never be printed, logged or committed. Read ch 44's push-notification rules (`02-book/6-out-in-the-world/44-email-and-notifications.md`) and apply only what fits a topic subscription.

**Files:**
- Create: `bench/notify.py`, `tests/test_notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `summary.json` shape from Task 8.
- Produces: `build_message(summary, run_date) -> (title, body)`, `send(topic, title, body, click, priority=2, opener=urlopen) -> int`, `notify(summary_path, run_date, failure, env, opener=urlopen) -> int` (0 on success or when `NTFY_TOPIC` is unset; 1 if sending failed). Called by `bench.cli notify` (already wired in Task 7).

- [ ] **Step 1: Write the failing tests**

`tests/test_notify.py`:

```python
import json

from bench.notify import build_message, notify, send


def summary(rows):
    names = ["control_random", "analog", "xgb_indicators"]
    return {
        "estimators": [{"name": n, "label": n.upper(), "kind": "control" if n.startswith("control") else "ml"} for n in names],
        "modes": {"live": {"rows": {n: rows.get(n, {"status": "ok", "n_days": 0, "day_return": None}) for n in names}}},
    }


def row(day_return, n_days=5, status="ok"):
    return {"status": status, "n_days": n_days, "day_return": day_return}


def test_first_day_message_has_no_results_yet():
    title, body = build_message(summary({}), "2026-01-06")
    assert "2026-01-06" in title and "First results appear" in body


def test_message_names_best_worst_and_beats_random():
    s = summary({"control_random": row(0.001), "analog": row(0.0215), "xgb_indicators": row(-0.0034)})
    _, body = build_message(s, "2026-01-06")
    assert "best ANALOG +2.15%" in body and "worst XGB_INDICATORS -0.34%" in body
    assert "1 of 2 beat random" in body and body.startswith("Day 5")


def test_failures_are_reported():
    s = summary({"control_random": row(0.0), "analog": row(0.01), "xgb_indicators": row(0.01, status="failed")})
    _, body = build_message(s, "2026-01-06")
    assert "Problem: XGB_INDICATORS" in body


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_send_builds_the_request():
    seen = {}

    def opener(req, timeout):
        seen.update(url=req.full_url, headers=dict(req.header_items()), data=req.data, method=req.get_method())
        return FakeResponse()

    assert send("secret-topic", "Title", "Body é", "https://x.example/", 2, opener) == 200
    assert seen["url"] == "https://ntfy.sh/secret-topic" and seen["method"] == "POST"
    assert seen["headers"]["Priority"] == "2" and seen["headers"]["Click"] == "https://x.example/"
    assert seen["data"] == "Body é".encode("utf-8")


def test_notify_skips_quietly_without_a_topic(tmp_path, capsys):
    assert notify(tmp_path / "none.json", "2026-01-06", False, {}) == 0
    assert "skipping" in capsys.readouterr().out


def test_notify_failure_message_and_no_topic_leak(tmp_path, capsys):
    calls = []

    def opener(req, timeout):
        calls.append(req)
        raise OSError("boom https://ntfy.sh/secret-topic")

    code = notify(tmp_path / "none.json", "2026-01-06", True, {"NTFY_TOPIC": "secret-topic", "RUN_URL": "https://r"}, opener)
    out = capsys.readouterr()
    assert code == 1 and calls
    assert "secret-topic" not in out.out + out.err


def test_notify_success_reads_the_summary(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(summary({})))
    sent = []

    def opener(req, timeout):
        sent.append(req.data.decode())
        return FakeResponse()

    assert notify(p, "2026-01-06", False, {"NTFY_TOPIC": "t", "SITE_URL": "https://s/"}, opener) == 0
    assert "First results appear" in sent[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_notify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.notify'`

- [ ] **Step 3: Implement `bench/notify.py`**

```python
import json
import urllib.request
from pathlib import Path


def _pct(v):
    return f"{v * 100:+.2f}%"


def build_message(summary, run_date):
    labels = {e["name"]: e["label"] for e in summary["estimators"]}
    rows = summary["modes"]["live"]["rows"]
    problems = [labels[n] for n, r in rows.items() if r["status"] in ("failed", "skipped_late")]
    active = {n: r for n, r in rows.items() if not n.startswith("control_") and r["n_days"] > 0}
    parts = []
    if not active:
        parts.append(f"Predictions logged for {run_date}. First results appear after the next session closes.")
    else:
        best = max(active, key=lambda n: active[n]["day_return"])
        worst = min(active, key=lambda n: active[n]["day_return"])
        rand = rows.get("control_random", {}).get("day_return")
        beat = sum(1 for r in active.values() if rand is not None and r["day_return"] > rand)
        day_n = max(r["n_days"] for r in rows.values())
        parts.append(
            f"Day {day_n}: best {labels[best]} {_pct(active[best]['day_return'])}, "
            f"worst {labels[worst]} {_pct(active[worst]['day_return'])}."
        )
        parts.append(f"{beat} of {len(active)} beat random.")
    if problems:
        parts.append("Problem: " + ", ".join(problems) + ".")
    return f"Prediction bench {run_date}", " ".join(parts)


def send(topic, title, body, click, priority=2, opener=urllib.request.urlopen):
    headers = {"Title": title, "Priority": str(priority)}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), method="POST", headers=headers
    )
    with opener(req, timeout=15) as resp:
        return resp.status


def notify(summary_path, run_date, failure, env, opener=urllib.request.urlopen):
    topic = env.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC is not set; skipping the notification.")
        return 0
    if failure:
        title = f"Prediction bench {run_date}"
        body = "The daily run failed. Open the run to see why."
        click = env.get("RUN_URL", "")
    else:
        summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        title, body = build_message(summary, run_date)
        click = env.get("SITE_URL", "")
    try:
        send(topic, title, body, click, 2, opener)
    except Exception as e:
        # Print only the exception type: its message can contain the URL, which holds the topic.
        print(f"notification failed: {type(e).__name__}")
        return 1
    return 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest -v`
Expected: the whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add bench/notify.py tests/test_notify.py
git commit -m "feat: ntfy notification that never prints the topic"
```

---

### Task 13: Workflows, publishing and owner setup

**Rulebook:** read ch 34 (`02-book/6-out-in-the-world/34-build-deploy-and-environments.md`), ch 43 again for scheduled-run overlap, and ch 36 (`02-book/6-out-in-the-world/36-observability-and-operations.md`). Apply what they require of a scheduled pipeline (a failed run is visible, not silent).

**Files:**
- Create: `.github/workflows/daily.yml`, `.github/workflows/backfill.yml`, `tests/test_workflows.py`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: CLI commands from Task 7, `scripts/verify_data.py` from Task 9.
- Produces: scheduled workflow `daily` (cron `30 0 * * *`), manual workflow `backfill`, GitHub Pages deployment of `site/`, ntfy notification. Job flow: `fetch` -> `predict` (matrix, one job per estimator, `fail-fast: false`) -> `aggregate` (verify, commit, build) -> `deploy` -> `notify`. Both workflows share the concurrency group `bench-data`.

- [ ] **Step 1: Write the failing workflow tests**

`tests/test_workflows.py`:

```python
from pathlib import Path

import yaml

from estimators.registry import REGISTRY

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def load(name):
    text = (WF / name).read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def triggers(doc):
    return doc.get("on", doc.get(True))  # PyYAML reads the bare key `on` as True


def test_daily_schedule_and_manual_trigger():
    _, doc = load("daily.yml")
    assert triggers(doc)["schedule"] == [{"cron": "30 0 * * *"}]
    assert "run_date" in triggers(doc)["workflow_dispatch"]["inputs"]


def test_daily_job_graph():
    _, doc = load("daily.yml")
    jobs = doc["jobs"]
    assert jobs["predict"]["strategy"]["fail-fast"] is False
    assert jobs["predict"]["needs"] == "fetch"
    assert set(jobs["aggregate"]["needs"]) == {"fetch", "predict"}
    assert "always()" in jobs["aggregate"]["if"]
    assert jobs["deploy"]["environment"]["name"] == "github-pages"
    assert "notify" in jobs


def test_workflows_never_overlap_on_data():
    for name in ("daily.yml", "backfill.yml"):
        _, doc = load(name)
        assert doc["concurrency"]["group"] == "bench-data"
        assert doc["concurrency"]["cancel-in-progress"] is False


def test_topic_only_ever_comes_from_the_secret():
    for name in ("daily.yml", "backfill.yml"):
        text, _ = load(name)
        for line in text.splitlines():
            if "NTFY_TOPIC" in line:
                assert "secrets.NTFY_TOPIC" in line, line
            assert "echo" not in line or "NTFY" not in line


def test_data_is_verified_before_it_is_committed():
    for name in ("daily.yml", "backfill.yml"):
        text, _ = load(name)
        assert text.index("verify_data.py") < text.index("git commit")


def test_registry_files_exist():
    for name, m in REGISTRY.items():
        module = m["target"].split(":")[0].replace(".", "/") + ".py"
        assert (ROOT / module).exists(), name
        if "requirements" in m:
            assert (ROOT / m["requirements"]).exists(), name
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_workflows.py -v`
Expected: FAIL with `FileNotFoundError` for `.github/workflows/daily.yml`

- [ ] **Step 3: Write `.github/workflows/daily.yml`**

```yaml
name: daily

on:
  schedule:
    - cron: "30 0 * * *"
  workflow_dispatch:
    inputs:
      run_date:
        description: "Run date (UTC, YYYY-MM-DD). Leave empty for today."
        required: false

concurrency:
  group: bench-data
  cancel-in-progress: false

permissions:
  contents: write
  pages: write
  id-token: write

jobs:
  fetch:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    outputs:
      estimators: ${{ steps.list.outputs.estimators }}
      run_date: ${{ steps.date.outputs.run_date }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - id: date
        env:
          INPUT_DATE: ${{ inputs.run_date }}
        run: echo "run_date=${INPUT_DATE:-$(date -u +%F)}" >> "$GITHUB_OUTPUT"
      - run: python -m bench.cli fetch
      - id: list
        run: echo "estimators=$(python -m bench.cli list)" >> "$GITHUB_OUTPUT"
      - uses: actions/upload-artifact@v4
        with:
          name: prices
          path: data/prices

  predict:
    needs: fetch
    runs-on: ubuntu-latest
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        estimator: ${{ fromJson(needs.fetch.outputs.estimators) }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - uses: actions/download-artifact@v4
        with:
          name: prices
          path: data/prices
      - uses: actions/cache@v4
        with:
          path: |
            data/cache
            ~/.cache/huggingface
          key: cache-${{ matrix.estimator }}-${{ github.run_id }}
          restore-keys: cache-${{ matrix.estimator }}-
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          REQ=$(python -m bench.cli requirements --estimator "${{ matrix.estimator }}")
          if [ -n "$REQ" ]; then pip install -r "$REQ"; fi
      - run: python -m bench.cli run --estimator "${{ matrix.estimator }}" --run-date "${{ needs.fetch.outputs.run_date }}"
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: est-${{ matrix.estimator }}
          path: data/live/estimators/${{ matrix.estimator }}
          if-no-files-found: ignore

  aggregate:
    needs: [fetch, predict]
    if: ${{ always() && needs.fetch.result == 'success' }}
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - uses: actions/download-artifact@v4
        with:
          name: prices
          path: data/prices
      - uses: actions/download-artifact@v4
        with:
          pattern: est-*
          path: artifacts
      - name: Merge estimator results
        run: |
          shopt -s nullglob
          for d in artifacts/est-*; do
            n="${d#artifacts/est-}"
            mkdir -p "data/live/estimators/$n"
            cp -r "$d"/. "data/live/estimators/$n"/
          done
      - name: Verify data
        run: python scripts/verify_data.py data
      - name: Commit data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data
          if ! git diff --cached --quiet; then
            git commit -m "data: run ${{ needs.fetch.outputs.run_date }}"
            git pull --rebase origin "${{ github.ref_name }}"
            git push origin "HEAD:${{ github.ref_name }}"
          fi
      - run: python -m bench.cli aggregate --run-date "${{ needs.fetch.outputs.run_date }}"
      - uses: actions/upload-artifact@v4
        with:
          name: site-data
          path: site/data
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: aggregate
    if: ${{ always() && needs.aggregate.result == 'success' }}
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4

  notify:
    needs: [fetch, aggregate, deploy]
    if: ${{ always() }}
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
      SITE_URL: https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}/
      RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - if: ${{ needs.deploy.result == 'success' }}
        uses: actions/download-artifact@v4
        with:
          name: site-data
          path: site/data
      - if: ${{ needs.deploy.result == 'success' }}
        run: python -m bench.cli notify --run-date "${{ needs.fetch.outputs.run_date }}"
      - if: ${{ needs.deploy.result != 'success' }}
        run: python -m bench.cli notify --failure --run-date "${{ needs.fetch.outputs.run_date }}"
```

The test `test_topic_only_ever_comes_from_the_secret` accepts the line `NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}` because it contains `secrets.NTFY_TOPIC`.

- [ ] **Step 4: Write `.github/workflows/backfill.yml`**

```yaml
name: backfill

on:
  workflow_dispatch:
    inputs:
      days:
        description: "Days to replay"
        required: false
        default: "365"

concurrency:
  group: bench-data
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  fetch:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    outputs:
      estimators: ${{ steps.list.outputs.estimators }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -m bench.cli fetch
      - id: list
        run: echo "estimators=$(python -m bench.cli list)" >> "$GITHUB_OUTPUT"
      - uses: actions/upload-artifact@v4
        with:
          name: prices
          path: data/prices

  backtest:
    needs: fetch
    runs-on: ubuntu-latest
    timeout-minutes: 340
    strategy:
      fail-fast: false
      matrix:
        estimator: ${{ fromJson(needs.fetch.outputs.estimators) }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - uses: actions/download-artifact@v4
        with:
          name: prices
          path: data/prices
      - uses: actions/cache@v4
        with:
          path: |
            data/cache
            ~/.cache/huggingface
          key: cache-${{ matrix.estimator }}-bt-${{ github.run_id }}
          restore-keys: cache-${{ matrix.estimator }}-
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          REQ=$(python -m bench.cli requirements --estimator "${{ matrix.estimator }}")
          if [ -n "$REQ" ]; then pip install -r "$REQ"; fi
      - run: python -m bench.cli backfill --estimator "${{ matrix.estimator }}" --days "${{ inputs.days }}"
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: bt-${{ matrix.estimator }}
          path: data/backtest/estimators/${{ matrix.estimator }}
          if-no-files-found: ignore

  commit:
    needs: [fetch, backtest]
    if: ${{ always() && needs.fetch.result == 'success' }}
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - uses: actions/download-artifact@v4
        with:
          name: prices
          path: data/prices
      - uses: actions/download-artifact@v4
        with:
          pattern: bt-*
          path: artifacts
      - name: Merge estimator results
        run: |
          shopt -s nullglob
          for d in artifacts/bt-*; do
            n="${d#artifacts/bt-}"
            mkdir -p "data/backtest/estimators/$n"
            cp -r "$d"/. "data/backtest/estimators/$n"/
          done
      - name: Verify data
        run: python scripts/verify_data.py data
      - name: Commit data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data
          if ! git diff --cached --quiet; then
            git commit -m "data: backtest replay"
            git pull --rebase origin "${{ github.ref_name }}"
            git push origin "HEAD:${{ github.ref_name }}"
          fi
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest -v`
Expected: the whole suite passes, including the 6 workflow tests.

- [ ] **Step 6: Commit locally**

```bash
git add .github tests/test_workflows.py
git commit -m "feat: daily and backfill workflows with isolated per-estimator jobs"
```

- [ ] **Step 7: Owner setup (needs the owner; do not do these silently)**

These steps publish the project and use the owner's GitHub account, so confirm each with the owner first.

1. **Create the public repo.** Ask the owner for the repo name (suggest a plain one, since a bland name and empty description reduce casual discovery, but remind them that public means anyone with the link can read everything). Run `gh auth status` first. After the owner confirms name and public visibility:
   ```bash
   gh repo create <name-the-owner-chose> --public --source . --push
   ```
2. **Enable GitHub Pages from Actions:**
   ```bash
   gh api -X POST "repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/pages" -f build_type=workflow
   ```
   If it reports that Pages already exists, run the same call with `-X PUT`.
3. **Create the ntfy topic.** The owner generates a private topic locally and keeps it to themselves (never paste it into the chat):
   ```bash
   python -c "import secrets; print('bench-' + secrets.token_urlsafe(16))"
   ```
   Then the owner installs the ntfy app on their phone and subscribes to that exact topic name, and runs `gh secret set NTFY_TOPIC` and pastes the topic at the prompt.
4. **Confirm Actions are allowed to write:** repo Settings > Actions > General > Workflow permissions: "Read and write permissions".

---

### Task 14: First cloud run, measured

**Files:**
- Create: `docs/runtime-notes.md`

- [ ] **Step 1: Run the backfill in the cloud**

```bash
gh workflow run backfill.yml -f days=365
gh run watch
```

Expected: every matrix job succeeds; the `commit` job pushes a "data: backtest replay" commit. Record each estimator's job duration (`gh run view --json jobs`) in `docs/runtime-notes.md`. If a job fails, read its log, fix the cause locally, push, and re-run (for a changed estimator, first delete `data/backtest/estimators/<name>` and push, so the replay starts clean).

- [ ] **Step 2: Run the daily workflow manually**

```bash
git pull
gh workflow run daily.yml
gh run watch
```

Expected: all jobs green, a "data: run <date>" commit if anything changed, the Pages deploy succeeds, and the owner's phone shows one low-priority ntfy message. If it runs outside the first 6 hours of the UTC day, every estimator will record `skipped_late` (this is correct behaviour, not a bug) and the message will say "Problem: ...". The Pages site and notification still prove the plumbing; the first real live predictions come from the 00:30 UTC schedule.

- [ ] **Step 3: Check the published site**

Open `https://<owner>.github.io/<repo>/` in the built-in browser (`navigate`). Check: Backtest view shows all estimators, Live view shows the empty state, the console has no errors, and the page works at mobile width. Ask the owner to confirm the ntfy message arrived and that tapping it opens the page.

- [ ] **Step 4: Check the free-tier budget**

From the job durations, compute total runner minutes per day (sum of all `predict` jobs plus fetch, aggregate, deploy, notify). The repo is public, so Actions minutes are free; record the numbers anyway, and record the longest single job against the 45 minute `timeout-minutes` in `daily.yml`. If any estimator's daily job is over 30 minutes, lower its cost (fewer assets per run is not allowed; change its window or model size) before it joins the schedule.

- [ ] **Step 5: Confirm the first scheduled run (next morning)**

The day after setup, check that a run started near 00:30 UTC: `gh run list --workflow daily.yml --limit 3`. Note how late GitHub started it. If it started after 06:00 UTC, the `skipped_late` guard fires: record the delay in `docs/runtime-notes.md` and ask the owner whether to widen `LIVE_WINDOW_HOURS` in `bench/runner.py` (the window must still end before the first US session opens at about 13:30 UTC).

- [ ] **Step 6: Commit**

```bash
git add docs/runtime-notes.md
git commit -m "docs: runtime measurements from the first cloud runs"
git push
```

---

### Task 15: Heavier estimators, one at a time, each gated

The owner's five tools plus Kronos, TimesFM and an LSTM. None of these can be written blind: the owner's repositories were never verified to install or run, and the model APIs below are candidates taken from each project's own documentation, to be confirmed by a short spike. **Each estimator is its own cycle (spike, adapter, contract test, backfill, commit), and an estimator that fails its spike is dropped or reimplemented and the decision is written down. Nothing enters the lineup unverified.**

**Rulebook:** read ch 5 again (licences, provenance) before each third-party estimator. Pin every third-party dependency to an exact commit or version. Never copy a third-party repository's code into this repo; depend on it by pinned reference so its licence is respected.

**Files (per estimator):**
- Create: `estimators/<name>/__init__.py`, `estimators/<name>/predict.py`, `estimators/<name>/requirements.txt`, `docs/estimators/<name>.md`
- Modify: `estimators/registry.py` (one entry), possibly `.github/workflows/*.yml` (only if it needs something the generic jobs do not provide)
- Shared (create once, first): `estimators/adapter.py`, `scripts/spike_estimator.py`

**Interfaces:**
- Consumes: `Estimator`, `Prediction`, the contract test (it automatically covers any new registry entry).
- Produces: `ClosesForecaster` adapter base class (below), one registry entry per estimator, one decision note per estimator.

- [ ] **Step 1: Create the shared adapter and the spike script**

`estimators/adapter.py`:

```python
import numpy as np

from estimators.base import Estimator, Prediction


class ClosesForecaster(Estimator):
    """Adapter for models that forecast future closes from a window of past candles.

    A subclass implements only `_forecast`. Everything else (windowing, minimum history,
    turning predicted closes into a Prediction with a path) is shared, so every such model
    is judged on the same footing.
    """

    window = 256
    horizon = 5
    min_rows = 300

    def _forecast(self, df, horizon):
        """df: the last `window` candles. Return `horizon` predicted future closes."""
        raise NotImplementedError

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if len(df) < self.min_rows:
                continue
            win = df.tail(self.window).reset_index(drop=True)
            closes = np.asarray(self._forecast(win, self.horizon), dtype=float)
            if closes.shape != (self.horizon,):
                raise ValueError(f"{self.name}: expected {self.horizon} closes, got shape {closes.shape}")
            last = float(win["close"].iloc[-1])
            out[a] = Prediction(float(closes[0] / last - 1.0), None, [float(x) for x in closes])
        return out
```

`scripts/spike_estimator.py`:

```python
import sys
import time

from bench.config import load_config
from bench.data import load_prices
from estimators import registry

name = sys.argv[1]
settings, assets = load_config("assets.yaml")
prices = load_prices("data/prices", assets)
hist = {s: prices[s].iloc[-400:].reset_index(drop=True) for s in ("SPY", "BTC-USD")}
est = registry.build(name)
t0 = time.time()
out = est.predict(hist, list(hist))
dt = time.time() - t0
print(out)
per_asset = dt / len(hist)
print(f"{dt:.1f}s for {len(hist)} assets = {per_asset:.1f}s per asset (includes model load)")
print(f"daily run for {len(assets)} assets: about {per_asset * len(assets) / 60:.1f} min on this machine")
print(f"one-year backfill at stride 1: about {per_asset * len(assets) * 365 / 3600:.1f} h on this machine")
```

Commit: `git add estimators/adapter.py scripts/spike_estimator.py && git commit -m "feat: shared adapter for close-forecasting models and a spike timing script"`.

- [ ] **Step 2: LSTM (own implementation, fully specified)**

`estimators/lstm/requirements.txt`:

```
--extra-index-url https://download.pytorch.org/whl/cpu
torch>=2.2
```

`estimators/lstm/predict.py` (empty `__init__.py` next to it):

```python
import os
from datetime import date
from pathlib import Path

import numpy as np
import torch
from torch import nn

from estimators.base import Estimator, Prediction

SEQ = 20          # days in each input window
SCALE = 50.0      # targets are scaled so typical daily returns are near 1
RETRAIN_DAYS = 7  # a cached model is reused for a week, then retrained
MIN_ROWS = SEQ + 50


def _cache_file():
    return Path(os.environ.get("BENCH_CACHE", "data/cache")) / "lstm" / "model.pt"


def _features(df):
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    ret = np.concatenate([[0.0], c[1:] / c[:-1] - 1.0])
    f = np.column_stack([ret, (h - l) / c, (c - o) / o]) / 0.02
    return np.clip(f, -10, 10)


def _windows(df):
    f, c = _features(df), df["close"].to_numpy(float)
    idx = range(SEQ, len(df) - 1)  # the window ends at day i, the target is day i -> i+1
    xs = np.stack([f[i - SEQ + 1 : i + 1] for i in idx])
    ys = np.array([c[i + 1] / c[i] - 1.0 for i in idx]) * SCALE
    return xs, ys


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(3, 32, batch_first=True)
        self.head = nn.Linear(32, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1]).squeeze(-1)


def _train(history):
    torch.manual_seed(0)
    parts = [_windows(df) for df in history.values()]
    X = torch.tensor(np.concatenate([p[0] for p in parts]), dtype=torch.float32)
    Y = torch.tensor(np.concatenate([p[1] for p in parts]), dtype=torch.float32)
    net = Net()
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    gen = torch.Generator().manual_seed(0)
    for _ in range(8):
        perm = torch.randperm(len(X), generator=gen)
        for i in range(0, len(X), 256):
            batch = perm[i : i + 256]
            opt.zero_grad()
            nn.functional.mse_loss(net(X[batch]), Y[batch]).backward()
            opt.step()
    return net


class Lstm(Estimator):
    """A small LSTM on 20-day windows of return, range and body, pooled across assets.

    Retrained weekly from the truncated history. A cached model is only reused when it was
    trained on or before the date being predicted, so a replay can never use a model that
    saw the future.
    """

    name = "lstm"

    def _model(self, history, asof):
        path = _cache_file()
        if path.exists():
            blob = torch.load(path, weights_only=True)  # the cache holds only tensors and a date string
            age = (date.fromisoformat(asof) - date.fromisoformat(blob["trained_asof"])).days
            if 0 <= age < RETRAIN_DAYS:
                net = Net()
                net.load_state_dict(blob["state"])
                return net
        net = _train(history)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state": net.state_dict(), "trained_asof": asof}, path)
        return net

    def predict(self, history, assets):
        usable = {a: df for a, df in history.items() if len(df) >= MIN_ROWS}
        if not usable:
            return {}
        asof = max(df["date"].iloc[-1] for df in usable.values())
        net = self._model(usable, asof)
        net.eval()
        out = {}
        with torch.no_grad():
            for a in assets:
                if a in usable:
                    x = torch.tensor(_features(usable[a])[-SEQ:][None], dtype=torch.float32)
                    out[a] = Prediction(float(net(x)[0]) / SCALE)
        return out
```

Add to `estimators/registry.py`:

```python
    "lstm": {
        "target": "estimators.lstm.predict:Lstm",
        "label": "LSTM on candle shape", "kind": "ml",
        "source": "Small PyTorch LSTM on 20-day windows; our own implementation",
        "license": "own code (uses PyTorch, BSD-3-Clause)", "original_code": False,
        "requirements": "estimators/lstm/requirements.txt",
    },
```

Edit `tests/test_estimator_contract.py`: add an autouse fixture at the top so cached models never touch the repo:

```python
@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_CACHE", str(tmp_path / "cache"))
```

Run: `pip install -r estimators/lstm/requirements.txt && python -m pytest tests/test_estimator_contract.py -v -k lstm`
Expected: passes (the first `predict` trains and caches, the second loads the cache; equality proves the cache round-trip is exact). Then `python scripts/spike_estimator.py lstm`, write `docs/estimators/lstm.md` (template below), set `backfill_stride` on the class if the printed backfill estimate exceeds 5 hours, run `python -m bench.cli backfill --estimator lstm --days 365`, `python scripts/verify_data.py data`, and commit.

Decision-note template, `docs/estimators/<name>.md`:

```markdown
# <name>
- Source: <URL, commit or version pinned>
- Licence: <read from the repo's LICENSE file, not from memory>
- Original code or reimplementation: <which>
- Installs on a clean GitHub runner: <yes/no, how>
- Spike result: <seconds per asset, projected daily minutes, projected backfill hours>
- Decision: <include as is | include with backfill_stride N | reimplement | drop>, because <reason>
```

- [ ] **Step 3: Kronos and TimesFM (pretrained; adapter plus spike)**

Create `estimators/timesfm/predict.py` and `estimators/kronos/predict.py` (each with an empty `__init__.py`), using the adapter. The model calls below are **candidates from each project's README at the time of writing; the spike confirms or corrects them, and the spike's working call is what gets committed.**

TimesFM candidate (`estimators/timesfm/requirements.txt`: the package version the spike installs, pinned):

```python
import numpy as np

from estimators.adapter import ClosesForecaster


class TimesFM(ClosesForecaster):
    name = "timesfm"
    window = 512
    horizon = 5

    def __init__(self):
        import timesfm  # imported here so the registry can list this estimator without the dependency

        self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
        self._model.compile(timesfm.ForecastConfig(
            max_context=512, max_horizon=8, normalize_inputs=True,
            use_continuous_quantile_head=True, force_flip_invariance=True,
            infer_is_positive=True, fix_quantile_crossing=True,
        ))

    def _forecast(self, df, horizon):
        point, _ = self._model.forecast(horizon=horizon, inputs=[df["close"].to_numpy(float)])
        return np.asarray(point[0], dtype=float)
```

Kronos candidate (the project ships as a repository, not a PyPI package; pin the commit and install it as the spike shows):

```python
import numpy as np
import pandas as pd
import torch

from estimators.adapter import ClosesForecaster


class Kronos(ClosesForecaster):
    name = "kronos"
    window = 400
    horizon = 5
    backfill_stride = 5  # lower or raise after the spike's timing

    def __init__(self):
        from model import Kronos as KronosModel, KronosPredictor, KronosTokenizer

        tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = KronosModel.from_pretrained("NeoQuasar/Kronos-small")
        self._predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

    def _forecast(self, df, horizon):
        torch.manual_seed(0)  # the model samples; seeding keeps the estimator deterministic
        x = df[["open", "high", "low", "close", "volume"]]
        x_ts = pd.to_datetime(df["date"])
        y_ts = pd.Series(pd.bdate_range(x_ts.iloc[-1] + pd.Timedelta(days=1), periods=horizon))
        pred = self._predictor.predict(
            df=x, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=horizon, T=1.0, top_p=0.9, sample_count=1
        )
        return pred["close"].to_numpy(float)
```

For each of the two:
1. **Confirm the source and licence.** Search for the official repository (the Kronos repo found during research looked like a fork; use the official one named in the Kronos paper, https://arxiv.org/pdf/2508.02739), read its `LICENSE`, and write `docs/estimators/<name>.md`. If the licence forbids redistribution or use here, drop it and say so.
2. **Install in a scratch virtualenv** (not the project's): follow the project's README. Record the pinned version or commit in `estimators/<name>/requirements.txt`.
3. **Spike:** add the registry entry (`kind: "pretrained"`, `original_code: True`), then `python scripts/spike_estimator.py <name>`. If the README call above is wrong, fix `_forecast` until the spike prints two finite predictions. This is the one step where the code is derived from running the library.
4. **Contract test:** `python -m pytest tests/test_estimator_contract.py -v -k <name>`. If `deterministic` fails, find the unseeded randomness and seed it.
5. **Backfill** with a `backfill_stride` chosen from the spike so the one-year replay fits in 5 hours on a GitHub runner (the spike machine is probably faster; multiply its estimate by 2). The dashboard already labels pretrained backtests "may be optimistic"; set the registry `kind` to `pretrained` so the notes apply.
6. `python scripts/verify_data.py data`, commit.

- [ ] **Step 4: The owner's four repositories (locate, verify, wrap or reimplement)**

For each of **CandleEdge**, **neural-candlestick**, **candlesticks_predictions** (the Transformer) and **big-data-stock-price-forecast**:

1. **Locate the repository.** Search GitHub for the name. If more than one plausible repository exists, show the owner the candidates and let them pick. Do not guess.
2. **Read** its README, `LICENSE` and entry points. Fill in the first four lines of the decision note.
3. **Spike in a scratch virtualenv:** install it exactly as its README says, then call its prediction entry point on 300 candles of SPY. Record: did it install, did it run, how long it took, and whether it can be called as a function on an in-memory DataFrame (not only via a notebook or script that reads its own files).
4. **Decide, and write the decision into the note:**
   - *Wrap* when it is callable and its licence allows depending on it: write `estimators/<name>/predict.py` as a `ClosesForecaster` subclass (if it forecasts closes) or an `Estimator` subclass (if it outputs a direction or return), pin the dependency to the commit in `requirements.txt`, set `original_code: True`.
   - *Reimplement* when it is not callable or will not install: write our own implementation of its core idea, set `original_code: False`, and credit the source in `source`. The analog estimator from Task 6 is the reimplementation of CandleEdge-style matching; if CandleEdge turns out to be usable as is, add it as a separate estimator and keep `analog` as the comparison.
   - *Drop* when the licence forbids it or the idea is unreproducible, and say why.
5. Registry entry, contract test, spike timing, backfill with an appropriate stride, `scripts/verify_data.py`, commit.

The candlesticks_predictions Transformer reports in its own README that its predicted candle sizes were coherent but their positions were not; record that expectation in its note so a bad result is read as confirmation, not surprise.

- [ ] **Step 5: Show predicted paths for the estimators that forecast several days**

The spec asks for the predicted path against the real one. Write the failing test first, in `tests/test_aggregate.py`:

```python
def test_paths_compare_predicted_closes_with_what_happened(tmp_path):
    from bench.aggregate import _paths

    st = Store(tmp_path / "live")
    st.save_prediction("kronos", "2026-01-03", {"predictions": {
        "AAA": {"asof": "2026-01-02", "expected_return": 0.01, "confidence": None,
                "path": [101.0, 102.0, 103.0]}}})
    out = _paths(st, "kronos", prices())
    assert out == [{"asset": "AAA", "asof": "2026-01-02", "predicted": [101.0, 102.0, 103.0], "actual": [102.0]}]
    assert _paths(st, "control_random", prices()) == []
```

Run it (expected: FAIL, `ImportError: cannot import name '_paths'`), then add to `bench/aggregate.py`:

```python
def _paths(store, name, prices, limit=25):
    """Predicted closes next to the closes that actually followed, for the latest prediction day."""
    preds = store.load_predictions(name)
    for run_date in sorted(preds, reverse=True):
        with_path = {a: p for a, p in preds[run_date]["predictions"].items() if p.get("path")}
        if not with_path:
            continue
        out = []
        for asset, p in sorted(with_path.items())[:limit]:
            df = prices.get(asset)
            after = df[df["date"] > p["asof"]]["close"].tolist() if df is not None else []
            out.append({
                "asset": asset, "asof": p["asof"], "predicted": p["path"],
                "actual": after[: len(p["path"])],
            })
        return out
    return []
```

and in `build_all`, after `details[n]["modes"][mode] = _detail(...)`, add `details[n]["modes"][mode]["paths"] = _paths(Store(Path(data_dir) / mode), n, prices)`. Run `python -m pytest tests/test_aggregate.py -v` (expected: pass).

In `site/app.js` `renderEstimator`, after the "By asset" section and only when `mode.paths && mode.paths.length`, append:

```js
  if (mode.paths && mode.paths.length) {
    view.append(el("h2", {}, "Predicted path vs what happened (latest prediction)"));
    for (const p of mode.paths) {
      const rows = p.predicted.map((v, i) => {
        const actual = p.actual[i];
        return el("tr", {},
          el("td", {}, `day +${i + 1}`), el("td", {}, v.toFixed(2)),
          el("td", {}, actual === undefined ? "pending" : actual.toFixed(2)),
          el("td", {}, actual === undefined ? "n/a" : `${signMark(actual - v)} ${fmtPct(actual / v - 1)}`));
      });
      view.append(el("details", { class: "day" }, el("summary", {}, `${p.asset} · predicted ${p.asof}`),
        el("div", { class: "tablewrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ...["Step", "Predicted close", "Actual close", "Actual vs predicted"].map((h) => el("th", {}, h)))),
          el("tbody", {}, ...rows)))));
    }
  }
```

Verify in the browser on `#/e/kronos` or `#/e/timesfm` once its backtest exists. Commit.

- [ ] **Step 6: Commit and push each estimator separately**

One commit per estimator: `git add estimators/<name> docs/estimators/<name>.md estimators/registry.py data && git commit -m "feat: <name> estimator (<decision>)"`. Push, then run the `backfill` workflow once for the new estimators (it replays only what is missing) and the `daily` workflow to confirm they appear in the matrix and on the dashboard.

---

### Task 16: Documentation and rulebook check

**Rulebook:** read ch 37 (`02-book/6-out-in-the-world/37-documentation-and-handover.md`), and re-read every chapter listed in the spec's section 13 as "applied" that you have not read yet during this build: ch 1-4, 6-12, 14-16, 18, 21, 24, 29, 40.

**Files:**
- Create: `README.md`, `docs/rulebook-checklist.md`, `tests/test_capabilities.py`
- Test: `tests/test_capabilities.py`

- [ ] **Step 1: Write the capability-drift test (the book's rule: used but undeclared is a finding)**

The declared capabilities are in the spec's section 13. This test detects the ones we deliberately do not have.

`tests/test_capabilities.py`:

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ALLOWED_URLS = {"http://www.w3.org/2000/svg"}


def site_sources():
    return [p for p in SITE.iterdir() if p.suffix in {".js", ".html", ".css"} and not p.name.endswith(".test.js")]


def test_site_makes_no_third_party_requests():
    for p in site_sources():
        for url in re.findall(r"https?://[^\s\"')]+", p.read_text(encoding="utf-8")):
            assert url in ALLOWED_URLS, f"{p.name} references {url}"


def test_site_sets_no_cookies():
    for p in site_sources():
        assert "document.cookie" not in p.read_text(encoding="utf-8"), p.name


def test_site_has_no_user_input_images_or_media():
    src = (SITE / "app.js").read_text(encoding="utf-8")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'el\("(img|audio|video|form|input|textarea|select)"', src)
    assert not re.search(r"<(img|audio|video|form|input|textarea|select)\b", html)


def test_no_secrets_or_topics_in_the_repo():
    for p in list(ROOT.glob("bench/*.py")) + list((ROOT / ".github").rglob("*.yml")) + [ROOT / "assets.yaml"]:
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"ntfy\.sh/[A-Za-z0-9_-]{6,}", line.replace("ntfy.sh/{topic}", "")), (p.name, line)
```

Run: `python -m pytest tests/test_capabilities.py -v`
Expected: 4 passed. If one fails, it has found a real capability the declaration missed: fix the code or update the declaration in the spec and `docs/rulebook-checklist.md`, never silence the test.

- [ ] **Step 2: Write `README.md`**

Contents, in this order, each section short: what the bench is and the one-line question it answers; the "experiment, not advice" note; how a day works (the five steps from the spec); how to read the dashboard (wallets, heatmaps, luck check, "too early to tell", the sanity badge, Live vs Backtest and why pretrained backtests may be optimistic); how to add an estimator (a folder with `predict.py`, an entry in `estimators/registry.py`, the contract test passing, a decision note in `docs/estimators/`); how to run locally (`pip install -r requirements-dev.txt`, `python -m pytest`, `node --test site/`, `python -m bench.cli fetch`, `python -m bench.cli backfill --estimator <name>`, `python -m bench.cli aggregate`, `python -m http.server -d site`); how to reset a backtest (delete `data/backtest/estimators/<name>` and run the backfill workflow); the secrets (`NTFY_TOPIC` only); the two stated approximations (crypto entry at the 00:00 UTC open with the prediction committed 30 to 60 minutes later; daily open-to-close trading ignores overnight gaps, which is why buy-and-hold is a reference line, not an account); and the licence note for third-party estimators.

- [ ] **Step 3: Write `docs/rulebook-checklist.md`**

One table, one row per chapter in the spec's "applied" and "waived" lists: chapter number and title, status (`done`, `waived`, `n/a`), the evidence (file, test or commit), and for every `waived` row the reason in one line (the spec's section 13 already gives them). Fill each `done` row from what the chapter's rules actually required, read from the chapter file, not from memory. Any rule a chapter requires that the build does not meet becomes a new row marked `open` with a one-line plan; report these to the owner.

- [ ] **Step 4: Run everything**

```bash
python -m pytest -v
node --test site/
python scripts/verify_data.py data
```

Expected: all pass, `data checks passed`.

- [ ] **Step 5: Commit and push**

```bash
git add README.md docs tests/test_capabilities.py
git commit -m "docs: README, rulebook checklist and capability-drift test"
git push
```

- [ ] **Step 6: Report to the owner**

Tell the owner: the dashboard URL; that the first live results appear after the first scheduled run and settle the following day; the "too early to tell" threshold is 60 live trading days; which estimators joined the lineup and which were dropped or reimplemented, with the reasons from `docs/estimators/`; any `open` rows in the rulebook checklist; and that an inconclusive result is a legitimate and likely outcome.
