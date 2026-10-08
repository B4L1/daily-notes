# V2 Part 1: Account Types and Realistic Costs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every model's stored predictions under five trading rules with per-asset costs, plus a majority-vote ensemble, without re-running any model.

**Architecture:** Models keep writing predictions only. A new scoring step recomputes every account (model x strategy) from scratch from predictions and prices on each run and overwrites its files, so scoring is deterministic, idempotent and re-runnable. Strategies are pure functions; the store, scorer, aggregate and workflows are thin around them.

**Tech Stack:** Python 3.12, pandas, PyYAML, pytest; GitHub Actions; existing vanilla JS dashboard (one label change only).

**Spec:** `docs/superpowers/specs/2026-10-08-v2-accounts-and-costs-design.md`

## Global Constraints

- Run tests with `.venv/Scripts/python -m pytest -q` and `node --test site/lib.test.js`. Bare `python` lacks the dependencies.
- No look-ahead: scoring for run date R only sees candles dated <= R - 1 day (`bench.runner.cut_history`). A decision for day T may never depend on a candle dated after T.
- A prediction with as-of date L targets the next candle after L for that asset.
- `cost(asset)` is that asset's `cost_round_trip` from `assets.yaml`. A strategy trades only when the expected return exceeds it. Entry and exit each cost half. Short borrow per calendar day held is `borrow_annual / 360`.
- Account day return = sum of (net return x weight) of its ledger rows that day / number of assets with a candle that day. Equity compounds from `start_equity` (10000) and never resets. A day return below -1 is floored at -1.
- Strategy names, exactly: `one_day`, `one_day_short`, `hold`, `top_picks`, `weekly`. Ensemble model name, exactly: `ensemble`.
- Scoring is a full recompute: same inputs give byte-identical files. Never append.
- Live and backtest stay in separate stores (`data/live`, `data/backtest`). Nothing from one may be read into the other.
- The repo is public. Commit nothing secret. Never commit `.superpowers/` or `.claude/`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (or the implementing model's own line).
- Do not push and do not run `gh` commands that change anything; the controller pushes.
- JSON written for the dashboard must contain no NaN or Infinity.

## Review Focus

1. A model stops producing predictions while its hold account has open positions: every position must be sold at the next session open, not held forever. (Task 4 test `test_missing_prediction_sells_at_next_open`.)
2. Weekend and holiday calendars: a stock position must be carried across days with no stock candle without a ledger row, and weekly positions count the asset's own sessions, not calendar days. (Task 4 `test_position_carried_over_days_without_a_candle`, Task 5 `test_five_sessions_not_five_calendar_days`.)
3. A prediction just below the asset's cost must not trade, while the same prediction on a cheaper asset must. (Task 2 `test_threshold_is_the_assets_own_cost`.)
4. Voting models disagree on the as-of date for an asset (one is a day stale): the ensemble must only count votes for the newest as-of, never mix days. (Task 6 `test_votes_only_count_for_the_newest_asof`.)
5. An account with no predictions at all (new model, or the weekly account of a model with no 5-day path): no files, and aggregate must not crash or emit NaN. (Task 7 `test_account_without_predictions_writes_nothing`, Task 8 `test_missing_accounts_are_skipped`.)

## File Structure

| File | Responsibility |
|---|---|
| `assets.yaml` | Per-asset `cost_round_trip`, `borrow_annual`; SPY and QQQ in group `etf` |
| `bench/config.py` | `Asset` gains the two cost fields; group and cost validation |
| `bench/costs.py` | `Costs`: round trip, half, borrow per day, group, per symbol |
| `bench/strategies/common.py` | Shared indexing of predictions and candles, ledger row builder, equity builder, `Result` |
| `bench/strategies/daily.py` | `one_day`, `one_day_short`, `top_picks` |
| `bench/strategies/hold.py` | `hold` |
| `bench/strategies/weekly.py` | `weekly` |
| `bench/strategies/__init__.py` | `STRATEGIES` registry: name -> function |
| `bench/ensemble.py` | Derive majority-vote predictions |
| `bench/store.py` | Account files (overwrite), `replace_predictions`, schema 2; V1 equity/ledger methods removed |
| `bench/scorer.py` | Run ensemble then every strategy for every model in one store |
| `bench/runner.py` | Predict only (settlement removed) |
| `bench/aggregate.py` | Read accounts; category split; ensemble in the model list |
| `bench/cli.py` | `score` command |
| `scripts/migrate_v2.py` | One-off: schema 1 -> 2, delete V1 ledgers |
| `scripts/verify_data.py` | Checks for accounts and crypto as-of |
| `.github/workflows/daily.yml`, `backfill.yml` | Score step before verify |
| `bench/broker.py`, `tests/test_broker.py` | Deleted in Task 8 |

---

### Task 1: Per-asset costs in the config

**Files:**
- Modify: `assets.yaml`, `bench/config.py`
- Create: `bench/costs.py`, `tests/test_costs.py`, `tests/fixtures/v1_control_random_equity.csv`
- Test: `tests/test_costs.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Asset(symbol, group, max_gap_days, cost_round_trip=0.001, borrow_annual=0.0)`; `bench.costs.Costs(assets)` with `round_trip(symbol) -> float`, `half(symbol) -> float`, `borrow_day(symbol) -> float`, `group(symbol) -> str`. `Settings.cost_round_trip` and `Settings.trade_threshold` still exist in this task (removed in Task 8).

- [ ] **Step 1: Save the V1 result that Task 2 must reproduce**

Run: `cp data/backtest/estimators/control_random/equity.csv tests/fixtures/v1_control_random_equity.csv` (create `tests/fixtures/` first). This file is the V1 equity of the random control under the flat 0.1% cost. It must be captured before anything changes.

- [ ] **Step 2: Write the failing tests**

`tests/test_costs.py`:

```python
import pytest

from bench.config import Asset, load_config
from bench.costs import Costs


def test_costs_per_asset():
    c = Costs([Asset("SPY", "etf", 5, 0.0001, 0.005), Asset("BTC-USD", "crypto", 0, 0.0025, 0.36)])
    assert c.round_trip("SPY") == 0.0001 and c.half("SPY") == 0.00005
    assert c.round_trip("BTC-USD") == 0.0025
    assert c.borrow_day("BTC-USD") == pytest.approx(0.001)
    assert c.group("SPY") == "etf"


def test_unknown_symbol_is_an_error():
    with pytest.raises(KeyError):
        Costs([]).round_trip("NOPE")


def test_repo_config_has_a_cost_for_every_asset():
    _, assets = load_config("assets.yaml")
    groups = {a.symbol: a.group for a in assets}
    assert groups["SPY"] == "etf" and groups["QQQ"] == "etf" and groups["AAPL"] == "stock"
    by_group = {a.group: a for a in assets}
    assert by_group["etf"].cost_round_trip == 0.0001
    assert by_group["stock"].cost_round_trip == 0.0005
    assert by_group["commodity"].cost_round_trip == 0.0003
    assert by_group["crypto"].cost_round_trip == 0.0025
    assert by_group["crypto"].borrow_annual == 0.10 and by_group["stock"].borrow_annual == 0.005


def test_bad_group_or_cost_is_rejected(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("assets:\n  - {symbol: X, group: bond, max_gap_days: 5}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="group"):
        load_config(p)
    p.write_text("assets:\n  - {symbol: X, group: stock, max_gap_days: 5, cost_round_trip: -0.1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cost"):
        load_config(p)
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_costs.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.costs'`.

- [ ] **Step 4: Implement**

In `bench/config.py` replace the `Asset` dataclass and add validation in `load_config`:

```python
import math

GROUPS = ("stock", "etf", "commodity", "crypto")


@dataclass(frozen=True)
class Asset:
    symbol: str
    group: str  # stock | etf | commodity | crypto
    max_gap_days: int  # how many days behind before the asset is reported stale
    cost_round_trip: float = 0.001  # buy and sell, as a fraction of the position
    borrow_annual: float = 0.0  # short borrow, per year
```

and, in `load_config`, after `assets = [Asset(**a) for a in raw.get("assets", [])]`:

```python
    for a in assets:
        if a.group not in GROUPS:
            raise ValueError(f"{a.symbol}: unknown group {a.group!r}")
        for field in ("cost_round_trip", "borrow_annual"):
            v = getattr(a, field)
            if not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
                raise ValueError(f"{a.symbol}: bad cost value {field}={v!r}")
```

`bench/costs.py`:

```python
class Costs:
    """What it costs to trade each asset. All values are fractions of the position."""

    def __init__(self, assets):
        self._assets = {a.symbol: a for a in assets}

    def round_trip(self, symbol):
        return float(self._assets[symbol].cost_round_trip)

    def half(self, symbol):
        return self.round_trip(symbol) / 2.0

    def borrow_day(self, symbol):
        return float(self._assets[symbol].borrow_annual) / 360.0

    def group(self, symbol):
        return self._assets[symbol].group
```

`assets.yaml` assets block (settings block unchanged in this task):

```yaml
assets:
  - {symbol: SPY,    group: etf,       max_gap_days: 5, cost_round_trip: 0.0001, borrow_annual: 0.005}
  - {symbol: QQQ,    group: etf,       max_gap_days: 5, cost_round_trip: 0.0001, borrow_annual: 0.005}
  - {symbol: AAPL,   group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: MSFT,   group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: NVDA,   group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: AMZN,   group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: GOOGL,  group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: META,   group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: TSLA,   group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: JPM,    group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: V,      group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: XOM,    group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: WMT,    group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: JNJ,    group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: AMD,    group: stock,     max_gap_days: 5, cost_round_trip: 0.0005, borrow_annual: 0.005}
  - {symbol: BTC-USD, group: crypto,   max_gap_days: 0, cost_round_trip: 0.0025, borrow_annual: 0.10}
  - {symbol: ETH-USD, group: crypto,   max_gap_days: 0, cost_round_trip: 0.0025, borrow_annual: 0.10}
  - {symbol: SOL-USD, group: crypto,   max_gap_days: 0, cost_round_trip: 0.0025, borrow_annual: 0.10}
  - {symbol: GLD,    group: commodity, max_gap_days: 5, cost_round_trip: 0.0003, borrow_annual: 0.005}
  - {symbol: SLV,    group: commodity, max_gap_days: 5, cost_round_trip: 0.0003, borrow_annual: 0.005}
  - {symbol: USO,    group: commodity, max_gap_days: 5, cost_round_trip: 0.0003, borrow_annual: 0.005}
```

Search the code for any place that treats SPY or QQQ as group `stock` (`grep -rn '"stock"' bench estimators scripts tests`) and adjust tests that assert a group; estimators do not read groups.

- [ ] **Step 5: Run all tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add assets.yaml bench/config.py bench/costs.py tests/test_costs.py tests/test_config.py tests/fixtures
git commit -m "feat: per-asset trading costs and an ETF group"
```

---

### Task 2: Strategy core and the one-day rule

**Files:**
- Create: `bench/strategies/__init__.py`, `bench/strategies/common.py`, `bench/strategies/daily.py`, `tests/test_strategy_daily.py`
- Test: `tests/test_strategy_daily.py`

**Interfaces:**
- Consumes: `bench.costs.Costs`.
- Produces, in `bench.strategies.common`:
  - `LEDGER_COLS`, `EQUITY_COLS` (lists, below).
  - `Result(ledger: list[dict], equity: list[dict], positions: list[dict])` (a `NamedTuple`).
  - `index_predictions(saved) -> dict[(asset, asof), dict]` where `saved` is `{run_date: payload}` as returned by `Store.load_predictions`.
  - `targets(prices) -> dict[(asset, asof), (date, open, close, prev_close)]`.
  - `sessions(prices) -> dict[date, list[asset]]`.
  - `by_target(preds, prices) -> dict[date, dict[asset, (pred, open, close, prev_close)]]`.
  - `hit_flag(expected, actual) -> int | None`.
  - `row(...)` and `finish(rows, prices, start_equity, open_after=None) -> list[dict]`.
- Produces, in `bench.strategies.daily`: `one_day(preds, prices, costs, start_equity) -> Result`. Every strategy in later tasks has this same signature.

- [ ] **Step 1: Write the failing tests**

`tests/test_strategy_daily.py`:

```python
import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from bench.config import Asset, load_config
from bench.costs import Costs
from bench.data import load_prices
from bench.store import Store
from bench.strategies import common, daily
from tests.helpers import candles

A = [Asset("AAA", "stock", 5, 0.001, 0.36), Asset("BBB", "etf", 5, 0.0001, 0.36)]


def px():
    return {
        "AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102)]),
        "BBB": candles([("2026-01-05", 50, 50, 50, 50), ("2026-01-06", 50, 51, 49, 49)]),
    }


def preds(**exp):
    return {(a, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None} for a, e in exp.items()}


def test_long_trade_pays_the_assets_cost():
    r = daily.one_day(preds(AAA=0.01), px(), Costs(A), 10000.0)
    row = r.ledger[0]
    assert row["date"] == "2026-01-06" and row["action"] == "day" and row["side"] == "long"
    assert row["net_ret"] == pytest.approx(0.02 - 0.001) and row["traded"] == 1 and row["hit"] == 1
    assert row["group"] == "stock" and row["cost"] == pytest.approx(0.001)
    # two assets had a session, one traded: 0.019 / 2
    assert r.equity[0]["day_return"] == pytest.approx(0.0095)
    assert r.equity[0]["equity"] == pytest.approx(10095.0)
    assert r.equity[0]["n_universe"] == 2 and r.equity[0]["n_traded"] == 1
    assert r.positions == []


def test_threshold_is_the_assets_own_cost():
    # 0.0005 is below AAA's cost (0.001) and above BBB's (0.0001)
    r = daily.one_day(preds(AAA=0.0005, BBB=0.0005), px(), Costs(A), 10000.0)
    traded = {x["asset"]: x["traded"] for x in r.ledger}
    assert traded == {"AAA": 0, "BBB": 1}


def test_untraded_prediction_still_gets_a_row_and_a_hit():
    r = daily.one_day(preds(AAA=-0.01), px(), Costs(A), 10000.0)
    assert r.ledger[0]["traded"] == 0 and r.ledger[0]["net_ret"] == 0.0 and r.ledger[0]["hit"] == 0
    assert r.equity[0]["equity"] == 10000.0


def test_zero_expected_return_has_no_hit():
    r = daily.one_day(preds(AAA=0.0), px(), Costs(A), 10000.0)
    assert r.ledger[0]["hit"] is None


def test_prediction_without_a_next_candle_is_not_settled():
    p = {("AAA", "2026-01-06"): {"asof": "2026-01-06", "expected_return": 0.5, "path": None}}
    r = daily.one_day(p, px(), Costs(A), 10000.0)
    assert r.ledger == [] and r.equity == []


def test_future_candles_do_not_change_past_decisions():
    base = daily.one_day(preds(AAA=0.01), px(), Costs(A), 10000.0)
    later = px()
    later["AAA"] = pd.concat([later["AAA"], candles([("2026-01-07", 500, 500, 500, 500)])], ignore_index=True)
    again = daily.one_day(preds(AAA=0.01), later, Costs(A), 10000.0)
    assert again.ledger[: len(base.ledger)] == base.ledger and again.equity[: len(base.equity)] == base.equity


def test_index_predictions_later_run_date_wins():
    saved = {
        "2026-01-06": {"predictions": {"AAA": {"asof": "2026-01-05", "expected_return": 1.0}}},
        "2026-01-07": {"predictions": {"AAA": {"asof": "2026-01-05", "expected_return": 2.0}}},
    }
    assert common.index_predictions(saved)[("AAA", "2026-01-05")]["expected_return"] == 2.0


def test_flat_cost_reproduces_the_v1_equity_of_the_random_control():
    """The refactor changes nothing but the costs: under 0.1% everywhere, V1 comes back."""
    fixture = Path("tests/fixtures/v1_control_random_equity.csv")
    root = Path("data/backtest/estimators/control_random/predictions")
    if not fixture.exists() or not root.exists():
        pytest.skip("repo data not present")
    _, assets = load_config("assets.yaml")
    flat = [dataclasses.replace(a, cost_round_trip=0.001) for a in assets]
    prices = load_prices(Path("data/prices"), assets)
    saved = {f.stem: __import__("json").loads(f.read_text(encoding="utf-8")) for f in sorted(root.glob("*.json"))}
    r = daily.one_day(common.index_predictions(saved), prices, Costs(flat), 10000.0)
    want = pd.read_csv(fixture, dtype={"date": str})
    got = pd.DataFrame(r.equity).set_index("date").loc[want["date"]]
    assert (got["equity"].to_numpy() - want["equity"].to_numpy()).__abs__().max() < 1e-6
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_daily.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.strategies'`.

- [ ] **Step 3: Implement**

`bench/strategies/common.py`:

```python
from typing import NamedTuple

LEDGER_COLS = [
    "date", "asset", "group", "asof", "side", "action", "entry", "exit", "expected_return",
    "traded", "net_ret", "weight", "cost", "actual_cc", "hit", "hit5",
]
EQUITY_COLS = ["date", "equity", "day_return", "n_universe", "n_traded", "n_open"]
FEE_ACTIONS = ("day", "open", "close")


class Result(NamedTuple):
    ledger: list
    equity: list
    positions: list


def index_predictions(saved):
    """{run_date: payload} -> {(asset, asof): prediction}. A later run date wins, as in V1."""
    out = {}
    for run_date in sorted(saved):
        for asset, p in saved[run_date]["predictions"].items():
            out[(asset, p["asof"])] = p
    return out


def targets(prices):
    """(asset, asof) -> (target date, open, close, previous close) for every consecutive candle pair."""
    out = {}
    for asset, df in prices.items():
        d, o, c = df["date"].tolist(), df["open"].tolist(), df["close"].tolist()
        for i in range(1, len(d)):
            out[(asset, d[i - 1])] = (d[i], float(o[i]), float(c[i]), float(c[i - 1]))
    return out


def sessions(prices):
    """date -> sorted assets that have a candle that day."""
    out = {}
    for asset, df in prices.items():
        for d in df["date"]:
            out.setdefault(d, []).append(asset)
    return {d: sorted(v) for d, v in out.items()}


def by_target(preds, prices):
    """target date -> {asset: (prediction, open, close, previous close)}."""
    tg = targets(prices)
    out = {}
    for (asset, asof), p in preds.items():
        if (asset, asof) in tg:
            t, o, c, prev_c = tg[(asset, asof)]
            out.setdefault(t, {})[asset] = (p, o, c, prev_c)
    return out


def hit_flag(expected, actual):
    """1 if the predicted direction was right, 0 if wrong, None when either side is flat."""
    if expected == 0 or actual == 0:
        return None
    return int((expected > 0) == (actual > 0))


def row(date, asset, costs, asof, side, action, entry, exit_, expected, traded, net, cost,
        actual_cc, hit, hit5=None, weight=1.0):
    return {
        "date": date, "asset": asset, "group": costs.group(asset), "asof": asof, "side": side,
        "action": action, "entry": entry, "exit": exit_, "expected_return": expected,
        "traded": int(traded), "net_ret": net, "weight": weight, "cost": cost,
        "actual_cc": actual_cc, "hit": hit, "hit5": hit5,
    }


def finish(rows, prices, start_equity, open_after=None):
    """Ledger rows -> equity rows. One row per date that has a ledger row."""
    sess = sessions(prices)
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    eq, out = float(start_equity), []
    for d in sorted(by_date):
        n = len(sess[d])
        total = sum(r["net_ret"] * r["weight"] for r in by_date[d])
        day = max(total / n, -1.0)
        eq *= 1.0 + day
        out.append({
            "date": d, "equity": eq, "day_return": day, "n_universe": n,
            "n_traded": sum(r["traded"] for r in by_date[d] if r["action"] in FEE_ACTIONS),
            "n_open": (open_after or {}).get(d, 0),
        })
    return out
```

`bench/strategies/daily.py`:

```python
from bench.strategies.common import Result, by_target, finish, hit_flag, row


def _run(preds, prices, costs, start_equity, short=False, top_n=None):
    rows = []
    days = by_target(preds, prices)
    for t in sorted(days):
        day = days[t]
        longs = {a for a, (p, *_x) in day.items() if p["expected_return"] > costs.round_trip(a)}
        if top_n is not None:
            ranked = sorted(longs, key=lambda a: (-day[a][0]["expected_return"], a))
            longs = set(ranked[:top_n])
        for asset in sorted(day):
            p, o, c, prev_c = day[asset]
            exp = p["expected_return"]
            rt = costs.round_trip(asset)
            gross = c / o - 1.0
            actual_cc = c / prev_c - 1.0
            if asset in longs:
                side, traded, net, cost = "long", 1, gross - rt, rt
            elif short and exp < -rt:
                cost = rt + costs.borrow_day(asset)
                side, traded, net = "short", 1, -gross - cost
            else:
                side, traded, net, cost = "none", 0, 0.0, 0.0
            rows.append(row(t, asset, costs, p["asof"], side, "day", o, c, exp, traded, net, cost,
                            actual_cc, hit_flag(exp, actual_cc)))
    return Result(rows, finish(rows, prices, start_equity), [])


def one_day(preds, prices, costs, start_equity):
    """Buy at the open, sell at the close, when the expected gain beats the asset's cost."""
    return _run(preds, prices, costs, start_equity)
```

`bench/strategies/__init__.py`:

```python
from bench.strategies import daily

STRATEGIES = {
    "one_day": daily.one_day,
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_daily.py`
Expected: all pass, including the V1 reproduction test (not skipped: confirm with `-rs` that nothing was skipped).

- [ ] **Step 5: Commit**

```bash
git add bench/strategies tests/test_strategy_daily.py
git commit -m "feat: strategy core and the one-day rule with per-asset costs"
```

---

### Task 3: Shorting and top picks

**Files:**
- Modify: `bench/strategies/daily.py`, `bench/strategies/__init__.py`, `tests/test_strategy_daily.py`

**Interfaces:**
- Consumes: `_run` from Task 2.
- Produces: `daily.one_day_short(preds, prices, costs, start_equity) -> Result`, `daily.top_picks(...) -> Result`; `STRATEGIES` gains `one_day_short` and `top_picks`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_strategy_daily.py`)

```python
def test_short_earns_when_the_price_falls():
    # BBB falls 50 -> 49: gross -0.02. cost 0.0001 + borrow 0.36/360 = 0.001
    r = daily.one_day_short(preds(BBB=-0.01), px(), Costs(A), 10000.0)
    row = r.ledger[0]
    assert row["side"] == "short" and row["traded"] == 1 and row["hit"] == 1
    assert row["net_ret"] == pytest.approx(0.02 - 0.0001 - 0.001)
    assert row["cost"] == pytest.approx(0.0011)


def test_short_loses_when_the_price_rises():
    r = daily.one_day_short(preds(AAA=-0.01), px(), Costs(A), 10000.0)
    assert r.ledger[0]["net_ret"] == pytest.approx(-0.02 - 0.001 - 0.001)


def test_short_account_still_goes_long_on_up_calls():
    r = daily.one_day_short(preds(AAA=0.01), px(), Costs(A), 10000.0)
    assert r.ledger[0]["side"] == "long" and r.ledger[0]["net_ret"] == pytest.approx(0.019)


def test_small_down_call_does_not_short():
    r = daily.one_day_short(preds(AAA=-0.0005), px(), Costs(A), 10000.0)
    assert r.ledger[0]["traded"] == 0


def test_long_only_account_ignores_down_calls():
    assert daily.one_day(preds(BBB=-0.01), px(), Costs(A), 10000.0).ledger[0]["traded"] == 0


def four():
    assets = [Asset(s, "stock", 5, 0.001, 0.0) for s in ("A1", "A2", "A3", "A4")]
    prices = {s: candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 101, 99, 101)]) for s in ("A1", "A2", "A3", "A4")}
    return assets, prices


def test_top_picks_takes_the_three_strongest():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None}
         for s, e in (("A1", 0.01), ("A2", 0.04), ("A3", 0.02), ("A4", 0.03))}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert sorted(x["asset"] for x in r.ledger if x["traded"]) == ["A2", "A3", "A4"]
    assert len(r.ledger) == 4  # the unpicked call still gets a row


def test_top_picks_with_fewer_than_three_qualifying():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": e, "path": None}
         for s, e in (("A1", 0.01), ("A2", 0.0005), ("A3", -0.02), ("A4", 0.0))}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert [x["asset"] for x in r.ledger if x["traded"]] == ["A1"]


def test_top_picks_ties_break_by_symbol():
    assets, prices = four()
    p = {(s, "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.01, "path": None} for s in ("A1", "A2", "A3", "A4")}
    r = daily.top_picks(p, prices, Costs(assets), 10000.0)
    assert sorted(x["asset"] for x in r.ledger if x["traded"]) == ["A1", "A2", "A3"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_daily.py`
Expected: FAIL with `AttributeError: module 'bench.strategies.daily' has no attribute 'one_day_short'`.

- [ ] **Step 3: Implement** (append to `bench/strategies/daily.py`)

```python
TOP_N = 3


def one_day_short(preds, prices, costs, start_equity):
    """As one_day, and also short at the open when the expected fall beats the asset's cost."""
    return _run(preds, prices, costs, start_equity, short=True)


def top_picks(preds, prices, costs, start_equity):
    """As one_day, but only the day's three strongest calls."""
    return _run(preds, prices, costs, start_equity, top_n=TOP_N)
```

and in `bench/strategies/__init__.py`:

```python
STRATEGIES = {
    "one_day": daily.one_day,
    "one_day_short": daily.one_day_short,
    "top_picks": daily.top_picks,
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_daily.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bench/strategies tests/test_strategy_daily.py
git commit -m "feat: one-day shorting and top-picks strategies"
```

---

### Task 4: The hold rule

**Files:**
- Create: `bench/strategies/hold.py`, `tests/test_strategy_hold.py`
- Modify: `bench/strategies/__init__.py`

**Interfaces:**
- Consumes: `common` helpers from Task 2.
- Produces: `hold.hold(preds, prices, costs, start_equity) -> Result`. `positions` items: `{"asset", "group", "side": "long", "entry_date", "entry", "last_date", "last", "unrealised"}`. `STRATEGIES["hold"]`.

Rule, exactly: iterate every date that has a candle, from the first prediction target date on. For each asset with a candle that day, let `p` be the prediction targeting that day (or none).
- Holding, `p` exists and `expected_return > 0`: keep. Net = close / previous close - 1. Action `hold`.
- Holding otherwise (no `p`, or `expected_return <= 0`): sell at the open. Net = open / previous close - 1 - half cost. Action `close`.
- Not holding and `expected_return > round-trip cost`: buy at the open. Net = close / open - 1 - half cost. Action `open`.
- Not holding, `p` exists but too weak: a row with `traded` 0, action `none`.
- Not holding and no `p`: no row.

- [ ] **Step 1: Write the failing tests**

`tests/test_strategy_hold.py`:

```python
import pytest

from bench.config import Asset
from bench.costs import Costs
from bench.strategies import hold
from tests.helpers import candles

A = [Asset("AAA", "stock", 5, 0.002, 0.0), Asset("CCC", "crypto", 0, 0.002, 0.0)]


def px():
    return {"AAA": candles([
        ("2026-01-05", 100, 100, 100, 100),
        ("2026-01-06", 100, 103, 99, 102),
        ("2026-01-07", 103, 105, 102, 104),
        ("2026-01-08", 105, 106, 102, 103),
    ])}


def P(pairs, asset="AAA"):
    return {(asset, asof): {"asof": asof, "expected_return": e, "path": None} for asof, e in pairs}


def test_three_day_hold_pays_cost_only_on_entry_and_exit():
    # enter 01-06, keep 01-07 (still positive), sell at the 01-08 open (turned negative)
    r = hold.hold(P([("2026-01-05", 0.01), ("2026-01-06", 0.0005), ("2026-01-07", -0.01)]), px(), Costs(A), 10000.0)
    acts = [(x["date"], x["action"]) for x in r.ledger]
    assert acts == [("2026-01-06", "open"), ("2026-01-07", "hold"), ("2026-01-08", "close")]
    nets = [x["net_ret"] for x in r.ledger]
    assert nets[0] == pytest.approx(102 / 100 - 1 - 0.001)
    assert nets[1] == pytest.approx(104 / 102 - 1)
    assert nets[2] == pytest.approx(105 / 104 - 1 - 0.001)
    want = 10000.0 * (1 + nets[0]) * (1 + nets[1]) * (1 + nets[2])
    assert r.equity[-1]["equity"] == pytest.approx(want)
    assert [e["n_traded"] for e in r.equity] == [1, 0, 1]
    assert [e["n_open"] for e in r.equity] == [1, 1, 0]
    assert r.positions == []


def test_weak_positive_call_does_not_open_but_keeps():
    # 0.0005 is below the 0.002 cost: no entry on its own
    r = hold.hold(P([("2026-01-05", 0.0005)]), px(), Costs(A), 10000.0)
    assert [(x["action"], x["traded"]) for x in r.ledger] == [("none", 0)]


def test_missing_prediction_sells_at_next_open():
    # the model predicts once, then stops: the position must not be held forever
    r = hold.hold(P([("2026-01-05", 0.01)]), px(), Costs(A), 10000.0)
    assert [(x["date"], x["action"]) for x in r.ledger] == [("2026-01-06", "open"), ("2026-01-07", "close")]
    assert r.ledger[1]["net_ret"] == pytest.approx(103 / 102 - 1 - 0.001)
    assert r.positions == []


def test_open_position_is_reported():
    r = hold.hold(P([("2026-01-05", 0.01), ("2026-01-06", 0.01), ("2026-01-07", 0.01)]), px(), Costs(A), 10000.0)
    pos = r.positions[0]
    assert pos["asset"] == "AAA" and pos["entry_date"] == "2026-01-06" and pos["entry"] == 100.0
    assert pos["last_date"] == "2026-01-08" and pos["last"] == 103.0
    assert pos["unrealised"] == pytest.approx(103 / 100 - 1 - 0.001)


def test_position_carried_over_days_without_a_candle():
    # AAA has no candle on the 7th (holiday); CCC trades every day. AAA is carried, no row, then kept.
    prices = {
        "AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102), ("2026-01-08", 105, 106, 102, 103)]),
        "CCC": candles([("2026-01-05", 10, 10, 10, 10), ("2026-01-06", 10, 10, 10, 10), ("2026-01-07", 10, 10, 10, 10), ("2026-01-08", 10, 10, 10, 10)]),
    }
    preds = P([("2026-01-05", 0.01), ("2026-01-06", 0.01)])
    r = hold.hold(preds, prices, Costs(A), 10000.0)
    aaa = [(x["date"], x["action"]) for x in r.ledger if x["asset"] == "AAA"]
    assert aaa == [("2026-01-06", "open"), ("2026-01-08", "hold")]
    assert [x for x in r.ledger if x["asset"] == "AAA"][1]["net_ret"] == pytest.approx(103 / 102 - 1)


def test_always_long_buys_once_and_holds():
    r = hold.hold(P([("2026-01-05", 1.0), ("2026-01-06", 1.0), ("2026-01-07", 1.0)]), px(), Costs(A), 10000.0)
    assert [x["action"] for x in r.ledger] == ["open", "hold", "hold"]
    assert sum(x["cost"] for x in r.ledger) == pytest.approx(0.001)


def test_future_candles_do_not_change_past_decisions():
    import pandas as pd
    preds = P([("2026-01-05", 0.01), ("2026-01-06", 0.0005), ("2026-01-07", -0.01)])
    base = hold.hold(preds, px(), Costs(A), 10000.0)
    later = px()
    later["AAA"] = pd.concat([later["AAA"], candles([("2026-01-09", 900, 900, 900, 900)])], ignore_index=True)
    again = hold.hold(preds, later, Costs(A), 10000.0)
    assert again.ledger[: len(base.ledger)] == base.ledger
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_hold.py`
Expected: FAIL with `ImportError: cannot import name 'hold'`.

- [ ] **Step 3: Implement**

`bench/strategies/hold.py`:

```python
from bench.strategies.common import Result, by_target, finish, hit_flag, row, sessions


def _candles(prices):
    """asset -> {date: (open, close, previous close or None)}."""
    out = {}
    for asset, df in prices.items():
        d, o, c = df["date"].tolist(), df["open"].tolist(), df["close"].tolist()
        out[asset] = {d[i]: (float(o[i]), float(c[i]), float(c[i - 1]) if i else None) for i in range(len(d))}
    return out


def hold(preds, prices, costs, start_equity):
    """Buy when the expected gain beats the round-trip cost; sell at the next open once the
    model stops expecting a gain. Costs are paid only on entry and on exit."""
    days = by_target(preds, prices)
    if not days:
        return Result([], [], [])
    first = min(days)
    sess = sessions(prices)
    cand = _candles(prices)
    held, rows, open_after, last_seen = {}, [], {}, {}
    for d in sorted(x for x in sess if x >= first):
        for asset in sess[d]:
            o, c, prev_c = cand[asset][d]
            if prev_c is None:
                continue
            entry = days.get(d, {}).get(asset)
            p = entry[0] if entry else None
            exp = p["expected_return"] if p else None
            asof = p["asof"] if p else None
            actual_cc = c / prev_c - 1.0
            hit = hit_flag(exp, actual_cc) if p else None
            half = costs.half(asset)
            if asset in held:
                if p and exp > 0:
                    rows.append(row(d, asset, costs, asof, "long", "hold", prev_c, c, exp, 1,
                                    actual_cc, 0.0, actual_cc, hit))
                    last_seen[asset] = (d, c)
                else:
                    rows.append(row(d, asset, costs, asof, "long", "close", prev_c, o, exp, 1,
                                    o / prev_c - 1.0 - half, half, actual_cc, hit))
                    del held[asset]
            elif p and exp > costs.round_trip(asset):
                rows.append(row(d, asset, costs, asof, "long", "open", o, c, exp, 1,
                                c / o - 1.0 - half, half, actual_cc, hit))
                held[asset] = (d, o)
                last_seen[asset] = (d, c)
            elif p:
                rows.append(row(d, asset, costs, asof, "none", "none", o, c, exp, 0, 0.0, 0.0, actual_cc, hit))
        open_after[d] = len(held)
    positions = [
        {
            "asset": a, "group": costs.group(a), "side": "long", "entry_date": held[a][0], "entry": held[a][1],
            "last_date": last_seen[a][0], "last": last_seen[a][1],
            "unrealised": last_seen[a][1] / held[a][1] - 1.0 - costs.half(a),
        }
        for a in sorted(held)
    ]
    return Result(rows, finish(rows, prices, start_equity, open_after), positions)
```

Add to `bench/strategies/__init__.py`: `from bench.strategies import daily, hold` and `"hold": hold.hold,` in `STRATEGIES`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_hold.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bench/strategies tests/test_strategy_hold.py
git commit -m "feat: hold strategy with costs on entry and exit only"
```

---

### Task 5: The weekly rule

**Files:**
- Create: `bench/strategies/weekly.py`, `tests/test_strategy_weekly.py`
- Modify: `bench/strategies/__init__.py`

**Interfaces:**
- Consumes: `common` helpers.
- Produces: `weekly.weekly(preds, prices, costs, start_equity) -> Result | None`. Returns `None` when no prediction carries a path of at least 5 values (the model has no weekly account). `STRATEGIES["weekly"]`. `weekly.HORIZON = 5`, `weekly.WEIGHT = 0.2`.

Rule, exactly. This is the precise reading of "one fifth of the account per day in 5-day positions": each asset has five slots of weight 0.2. For a prediction with as-of L and a path of at least 5 values, the 5-day expected return is `path[4] / (close on L) - 1`. On the target session (session 1) the asset opens a new slot when that value beats the round-trip cost: net = close / open - 1 - half cost. On its sessions 2 to 5 the slot earns close / previous close - 1. On session 5 it also pays the exit half and closes. Sessions are that asset's own candles, so a stock slot opened on a Friday closes the following Thursday. An asset can have at most five open slots, so exposure never exceeds its share. Every prediction with a path gets a row on session 1 (traded or not), and on session 5 its 5-day hit is recorded in `hit5`: for traded slots on the `close` row, for untraded predictions on a `mark` row with net 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_strategy_weekly.py`:

```python
import pytest

from bench.config import Asset
from bench.costs import Costs
from bench.strategies import weekly
from tests.helpers import candles

A = [Asset("AAA", "stock", 5, 0.002, 0.0)]
# session: 0       1        2        3        4        5        6
OPEN = [100, 100, 102, 103, 101, 104, 106]
CLOSE = [100, 102, 103, 101, 104, 106, 105]
DATES = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]


def px():
    return {"AAA": candles([(d, o, max(o, c), min(o, c), c) for d, o, c in zip(DATES, OPEN, CLOSE)])}


def P(asof, last, exp5):
    return {("AAA", asof): {"asof": asof, "expected_return": 0.0, "path": [last] * 4 + [last * (1 + exp5)]}}


def test_one_slot_runs_five_sessions():
    r = weekly.weekly(P("2026-01-05", 100.0, 0.05), px(), Costs(A), 10000.0)
    acts = [(x["date"], x["action"]) for x in r.ledger]
    assert acts == [(DATES[1], "open"), (DATES[2], "hold"), (DATES[3], "hold"), (DATES[4], "hold"), (DATES[5], "close")]
    nets = [x["net_ret"] for x in r.ledger]
    assert nets[0] == pytest.approx(102 / 100 - 1 - 0.001)
    assert nets[1] == pytest.approx(103 / 102 - 1)
    assert nets[4] == pytest.approx(106 / 104 - 1 - 0.001)
    assert all(x["weight"] == 0.2 for x in r.ledger)
    want = 10000.0
    for n in nets:
        want *= 1 + 0.2 * n
    assert r.equity[-1]["equity"] == pytest.approx(want)
    # 5-day call: predicted up, 106 vs 100 at the as-of close
    assert r.ledger[-1]["hit5"] == 1 and r.ledger[0]["hit5"] is None
    assert r.positions == []


def test_five_sessions_not_five_calendar_days():
    # opened Tuesday 01-06; the weekend has no candle; closes Monday 01-12 (its fifth session)
    r = weekly.weekly(P("2026-01-05", 100.0, 0.05), px(), Costs(A), 10000.0)
    assert r.ledger[-1]["date"] == "2026-01-12"


def test_weak_five_day_call_is_marked_but_not_traded():
    r = weekly.weekly(P("2026-01-05", 100.0, 0.001), px(), Costs(A), 10000.0)
    assert [(x["date"], x["action"], x["traded"]) for x in r.ledger] == [(DATES[1], "none", 0), (DATES[5], "mark", 0)]
    assert r.ledger[1]["hit5"] == 1 and r.ledger[1]["net_ret"] == 0.0


def test_down_call_is_marked_with_its_hit():
    r = weekly.weekly(P("2026-01-05", 100.0, -0.05), px(), Costs(A), 10000.0)
    assert r.ledger[-1]["action"] == "mark" and r.ledger[-1]["hit5"] == 0


def test_overlapping_slots_and_open_positions():
    preds = {**P("2026-01-05", 100.0, 0.05), **P("2026-01-06", 102.0, 0.05)}
    r = weekly.weekly(preds, px(), Costs(A), 10000.0)
    on_07 = [x for x in r.ledger if x["date"] == DATES[2]]
    assert sorted(x["action"] for x in on_07) == ["hold", "open"]
    # the second slot is still open after the last candle (its fifth session has not happened)
    assert len(r.positions) == 0 or r.positions[0]["entry_date"] == DATES[2]
    last = [x for x in r.ledger if x["date"] == DATES[6]]
    assert [x["action"] for x in last] == ["close"]


def test_model_without_paths_has_no_weekly_account():
    p = {("AAA", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.5, "path": None}}
    assert weekly.weekly(p, px(), Costs(A), 10000.0) is None


def test_short_path_is_ignored():
    p = {("AAA", "2026-01-05"): {"asof": "2026-01-05", "expected_return": 0.5, "path": [101.0, 102.0]}}
    assert weekly.weekly(p, px(), Costs(A), 10000.0) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_weekly.py`
Expected: FAIL with `ImportError: cannot import name 'weekly'`.

- [ ] **Step 3: Implement**

`bench/strategies/weekly.py`:

```python
from bench.strategies.common import Result, finish, hit_flag, row

HORIZON = 5
WEIGHT = 1.0 / HORIZON


def weekly(preds, prices, costs, start_equity):
    """Five overlapping 5-session slots per asset, each a fifth of the asset's share.

    Returns None for a model whose predictions carry no 5-day path.
    """
    usable = {k: p for k, p in preds.items() if p.get("path") and len(p["path"]) >= HORIZON}
    if not usable:
        return None
    rows, positions, open_after = [], [], {}
    for asset in sorted(prices):
        df = prices[asset]
        d, o, c = df["date"].tolist(), [float(x) for x in df["open"]], [float(x) for x in df["close"]]
        rt, half = costs.round_trip(asset), costs.half(asset)
        slots = []  # (start index, expected 5-day return, traded, asof)
        for i in range(1, len(d)):
            p = usable.get((asset, d[i - 1]))
            if p is not None:
                exp5 = float(p["path"][HORIZON - 1]) / c[i - 1] - 1.0
                slots.append((i, exp5, exp5 > rt, p["asof"]))
            actual_cc = c[i] / c[i - 1] - 1.0
            for start, exp5, traded, asof in slots:
                age = i - start
                if age < 0 or age >= HORIZON:
                    continue
                last = age == HORIZON - 1
                hit5 = hit_flag(exp5, c[i] / c[start - 1] - 1.0) if last else None
                if not traded:
                    if age == 0:
                        rows.append(row(d[i], asset, costs, asof, "none", "none", o[i], c[i], exp5, 0, 0.0, 0.0,
                                        actual_cc, None, None, WEIGHT))
                    elif last:
                        rows.append(row(d[i], asset, costs, asof, "none", "mark", o[i], c[i], exp5, 0, 0.0, 0.0,
                                        actual_cc, None, hit5, WEIGHT))
                    continue
                if age == 0:
                    rows.append(row(d[i], asset, costs, asof, "long", "open", o[i], c[i], exp5, 1,
                                    c[i] / o[i] - 1.0 - half, half, actual_cc, None, None, WEIGHT))
                elif last:
                    rows.append(row(d[i], asset, costs, asof, "long", "close", c[i - 1], c[i], exp5, 1,
                                    actual_cc - half, half, actual_cc, None, hit5, WEIGHT))
                else:
                    rows.append(row(d[i], asset, costs, asof, "long", "hold", c[i - 1], c[i], exp5, 1,
                                    actual_cc, 0.0, actual_cc, None, None, WEIGHT))
            still = sum(1 for start, _e, traded, _a in slots if traded and 0 <= i - start < HORIZON - 1)
            open_after[d[i]] = open_after.get(d[i], 0) + still
        n = len(d) - 1
        for start, exp5, traded, asof in slots:
            if traded and n - start < HORIZON - 1:
                positions.append({
                    "asset": asset, "group": costs.group(asset), "side": "long", "entry_date": d[start],
                    "entry": o[start], "last_date": d[n], "last": c[n],
                    "unrealised": c[n] / o[start] - 1.0 - half,
                })
    rows.sort(key=lambda r: (r["date"], r["asset"], r["asof"]))
    return Result(rows, finish(rows, prices, start_equity, open_after), positions)
```

Fix the overlapping test's loose assertion once the code runs: with these seven candles the second slot opens on `2026-01-07` (session index 2) and its fifth session is index 6 (`2026-01-13`), so it closes on the last candle and `positions` is empty. Replace `assert len(r.positions) == 0 or r.positions[0]["entry_date"] == DATES[2]` with `assert r.positions == []` if that is what you observe, and add this test for an open slot:

```python
def test_open_slot_is_reported():
    r = weekly.weekly(P("2026-01-08", 101.0, 0.05), px(), Costs(A), 10000.0)
    assert r.positions[0]["entry_date"] == "2026-01-09" and r.positions[0]["last_date"] == "2026-01-13"
    assert r.equity[-1]["n_open"] == 1
```

Add to `bench/strategies/__init__.py`: import `weekly` and `"weekly": weekly.weekly,`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_strategy_weekly.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bench/strategies tests/test_strategy_weekly.py
git commit -m "feat: weekly strategy with five overlapping slots per asset"
```

---

### Task 6: The majority-vote ensemble

**Files:**
- Create: `bench/ensemble.py`, `tests/test_ensemble.py`

**Interfaces:**
- Consumes: `bench.costs.Costs`.
- Produces: `ensemble.NAME = "ensemble"`, `ensemble.LABEL = "Ensemble (majority vote)"`, `ensemble.derive(saved_by_model, costs) -> dict[run_date, payload]` where `saved_by_model` is `{model: {run_date: payload}}` for the VOTING models only and each returned payload has the same shape as a prediction file: `{"schema_version": 2, "estimator": "ensemble", "run_date": ..., "created_at": None, "predictions": {asset: {"asof", "expected_return", "confidence": None, "path": None}}}`.

Rule, exactly: per run date and asset, take the newest as-of among the voters' predictions; only votes with that as-of count. `n` = number of such votes. Up vote: `expected_return > round_trip(asset)`. Down vote: `expected_return < -round_trip(asset)`. Result `+1.0` if up votes > n / 2, `-1.0` if down votes > n / 2, else `0.0`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ensemble.py`:

```python
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
    assert p["predictions"]["AAA"] == {"asof": "2026-01-05", "expected_return": 1.0, "confidence": None, "path": None}


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_ensemble.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.ensemble'`.

- [ ] **Step 3: Implement**

`bench/ensemble.py`:

```python
NAME = "ensemble"
LABEL = "Ensemble (majority vote)"
SCHEMA_VERSION = 2


def derive(saved_by_model, costs):
    """Majority vote of the voting models, per run date and asset. Controls must not be passed in."""
    run_dates = sorted({rd for saved in saved_by_model.values() for rd in saved})
    out = {}
    for rd in run_dates:
        votes = {}  # asset -> list of (asof, expected_return)
        for model in sorted(saved_by_model):
            payload = saved_by_model[model].get(rd)
            if not payload:
                continue
            for asset, p in payload["predictions"].items():
                votes.setdefault(asset, []).append((p["asof"], float(p["expected_return"])))
        preds = {}
        for asset in sorted(votes):
            newest = max(a for a, _e in votes[asset])
            exps = [e for a, e in votes[asset] if a == newest]
            rt = costs.round_trip(asset)
            up = sum(1 for e in exps if e > rt)
            down = sum(1 for e in exps if e < -rt)
            value = 1.0 if up > len(exps) / 2 else (-1.0 if down > len(exps) / 2 else 0.0)
            preds[asset] = {"asof": newest, "expected_return": value, "confidence": None, "path": None}
        if preds:
            out[rd] = {
                "schema_version": SCHEMA_VERSION, "estimator": NAME, "run_date": rd,
                "created_at": None, "predictions": preds,
            }
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_ensemble.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bench/ensemble.py tests/test_ensemble.py
git commit -m "feat: majority-vote ensemble as a derived prediction set"
```

---

### Task 7: Account storage, the scorer and the `score` command

**Files:**
- Modify: `bench/store.py`, `bench/cli.py`, `tests/test_store.py`, `tests/test_cli.py`
- Create: `bench/scorer.py`, `tests/test_scorer.py`

**Interfaces:**
- Consumes: `STRATEGIES`, `common.LEDGER_COLS`, `common.EQUITY_COLS`, `common.index_predictions`, `ensemble.derive`, `ensemble.NAME`, `Costs`, `bench.runner.cut_history`, `estimators.registry.REGISTRY` (each entry has a `"kind"`; controls have `kind == "control"`).
- Produces, in `Store`:
  - `write_account(model, strategy, result)` where `result` is a `common.Result`: overwrites `accounts/<model>/<strategy>/{ledger.csv,equity.csv,positions.json}`; with an empty ledger it removes those files instead.
  - `load_account(model, strategy) -> (equity_df, ledger_df)`, empty frames with the right columns when missing.
  - `load_positions(model, strategy) -> list`.
  - `replace_predictions(model, by_run_date)`: overwrites the model's whole predictions folder.
  - The V1 methods (`load_equity`, `load_ledger`, `append_equity`, `append_ledger`) stay in this task; Task 8 removes them.
- Produces: `scorer.score_store(store, prices, assets, settings, registry) -> dict[(model, strategy), int]` (settled days per account) and `scorer.models(registry) -> list[str]` (registry names plus `ensemble`). CLI: `python -m bench.cli score [--mode live|backtest|all] [--run-date YYYY-MM-DD]`.
- `SCHEMA_VERSION` stays 1 in this task. Task 9 bumps it with the migration.

- [ ] **Step 1: Write the failing tests**

`tests/test_scorer.py`:

```python
import pytest

from bench.config import Asset, Settings
from bench.scorer import models, score_store
from bench.store import Store
from tests.helpers import candles

ASSETS = [Asset("AAA", "stock", 5, 0.001, 0.0)]
REG = {
    "control_random": {"kind": "control"},
    "m1": {"kind": "ml"},
    "m2": {"kind": "ml"},
    "m3": {"kind": "ml"},
}


def px():
    return {"AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102), ("2026-01-07", 102, 104, 101, 103)])}


def save(store, model, exp, path=None):
    store.save_prediction(model, "2026-01-06", {
        "schema_version": 1, "estimator": model, "run_date": "2026-01-06", "created_at": None,
        "predictions": {"AAA": {"asof": "2026-01-05", "expected_return": exp, "confidence": None, "path": path}},
    })


def test_models_adds_the_ensemble():
    assert models(REG) == ["control_random", "m1", "m2", "m3", "ensemble"]


def test_scores_every_strategy_and_the_ensemble(tmp_path):
    st = Store(tmp_path)
    save(st, "control_random", -1.0)
    for m in ("m1", "m2", "m3"):
        save(st, m, 0.01)
    done = score_store(st, px(), ASSETS, Settings(), REG)
    assert done[("m1", "one_day")] == 1 and done[("m1", "hold")] == 2
    eq, led = st.load_account("m1", "one_day")
    assert eq["equity"].iloc[0] == pytest.approx(10190.0) and led["traded"].tolist() == [1]
    # the control does not vote: three up votes -> ensemble long
    assert st.load_predictions("ensemble")["2026-01-06"]["predictions"]["AAA"]["expected_return"] == 1.0
    assert st.load_account("ensemble", "one_day")[0]["equity"].iloc[0] == pytest.approx(10190.0)
    # the random control is scored too, under every strategy (it is each strategy's baseline)
    assert len(st.load_account("control_random", "one_day_short")[0]) == 1


def test_account_without_predictions_writes_nothing(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01)  # no path: no weekly account; m2, m3, control have no predictions at all
    done = score_store(st, px(), ASSETS, Settings(), REG)
    assert ("m1", "weekly") not in done and ("m2", "one_day") not in done
    assert not (tmp_path / "accounts" / "m1" / "weekly").exists()
    assert not (tmp_path / "accounts" / "m2").exists()
    eq, led = st.load_account("m2", "one_day")
    assert eq.empty and led.empty and st.load_positions("m2", "hold") == []


def test_scoring_twice_is_byte_identical_and_survives_deleted_positions(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01, path=[101, 102, 103, 104, 110])
    score_store(st, px(), ASSETS, Settings(), REG)
    files = sorted(p for p in (tmp_path / "accounts").rglob("*") if p.is_file())
    first = {p: p.read_bytes() for p in files}
    (tmp_path / "accounts" / "m1" / "hold" / "positions.json").unlink()
    score_store(st, px(), ASSETS, Settings(), REG)
    assert {p: p.read_bytes() for p in files} == first


def test_stale_account_files_are_removed(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01)
    score_store(st, px(), ASSETS, Settings(), REG)
    for f in (tmp_path / "estimators" / "m1" / "predictions").glob("*.json"):
        f.unlink()
    score_store(st, px(), ASSETS, Settings(), REG)
    assert not (tmp_path / "accounts" / "m1" / "one_day" / "equity.csv").exists()


def test_non_finite_result_fails_loudly_and_writes_nothing(tmp_path):
    st = Store(tmp_path)
    save(st, "m1", 0.01)
    bad = px()
    bad["AAA"].loc[1, "close"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        score_store(st, bad, ASSETS, Settings(), REG)
    assert not (tmp_path / "accounts" / "m1" / "one_day" / "equity.csv").exists()
```

Append to `tests/test_cli.py` (follow the file's existing fixture style for `BENCH_DATA` and `BENCH_ASSETS`; the test below is self-contained):

```python
def test_score_command_writes_accounts(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone

    from bench import cli
    from tests.helpers import random_walk

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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_scorer.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.scorer'`.

- [ ] **Step 3: Implement the store methods** (add to `class Store` in `bench/store.py`; add `import os` and `from bench.strategies.common import EQUITY_COLS as ACCT_EQUITY_COLS, LEDGER_COLS as ACCT_LEDGER_COLS` at the top)

```python
    def acct_dir(self, model, strategy):
        return self.root / "accounts" / model / strategy

    def write_account(self, model, strategy, result):
        """Overwrite one account's files. An empty ledger removes them."""
        d = self.acct_dir(model, strategy)
        names = ("ledger.csv", "equity.csv", "positions.json")
        if not result.ledger:
            for n in names:
                (d / n).unlink(missing_ok=True)
            for p in (d, d.parent):
                if p.exists() and not any(p.iterdir()):
                    p.rmdir()
            return
        d.mkdir(parents=True, exist_ok=True)
        texts = {
            "ledger.csv": pd.DataFrame(result.ledger, columns=ACCT_LEDGER_COLS).to_csv(index=False, lineterminator="\n"),
            "equity.csv": pd.DataFrame(result.equity, columns=ACCT_EQUITY_COLS).to_csv(index=False, lineterminator="\n"),
            "positions.json": json.dumps(result.positions, indent=1, sort_keys=True) + "\n",
        }
        for n, text in texts.items():
            tmp = d / f".{n}.tmp"
            tmp.write_text(text, encoding="utf-8", newline="")
            os.replace(tmp, d / n)

    def load_account(self, model, strategy):
        d = self.acct_dir(model, strategy)
        out = []
        for fname, cols in (("equity.csv", ACCT_EQUITY_COLS), ("ledger.csv", ACCT_LEDGER_COLS)):
            p = d / fname
            if not p.exists():
                out.append(pd.DataFrame(columns=cols))
                continue
            df = pd.read_csv(p, dtype={"date": str, "asof": str, "asset": str})
            if list(df.columns) != cols:
                raise SchemaMismatch(f"{p} has columns {list(df.columns)}, expected {cols}")
            out.append(df)
        return out[0], out[1]

    def load_positions(self, model, strategy):
        p = self.acct_dir(model, strategy) / "positions.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def replace_predictions(self, model, by_run_date):
        """Overwrite a derived model's whole prediction set."""
        d = self.root / "estimators" / model / "predictions"
        if d.exists():
            for f in d.glob("*.json"):
                if f.stem not in by_run_date:
                    f.unlink()
        for run_date, payload in by_run_date.items():
            self.save_prediction(model, run_date, payload)
```

`est_dir` creates the folder as a side effect; `load_predictions` of a model with no data therefore creates an empty `estimators/<model>` folder. That is existing behaviour and harmless; do not change it.

- [ ] **Step 4: Implement the scorer**

`bench/scorer.py`:

```python
import math

from bench import ensemble
from bench.costs import Costs
from bench.strategies import STRATEGIES
from bench.strategies.common import Result, index_predictions

CHECKED = ("net_ret", "entry", "exit", "expected_return", "cost", "actual_cc")


def models(registry):
    """Every model that has accounts: the registry's estimators plus the derived ensemble."""
    return list(registry) + [ensemble.NAME]


def _check(model, strategy, result):
    for r in result.ledger:
        for k in CHECKED:
            v = r[k]
            if v is not None and not math.isfinite(v):
                raise ValueError(f"non-finite {k} in {model}/{strategy} on {r['date']} {r['asset']}")
    for e in result.equity:
        if not (math.isfinite(e["equity"]) and math.isfinite(e["day_return"])):
            raise ValueError(f"non-finite equity in {model}/{strategy} on {e['date']}")


def score_store(store, prices, assets, settings, registry):
    """Recompute every account in one store from its predictions. Returns settled days per account.

    Everything is computed before anything is written, so a failure leaves the store untouched.
    """
    costs = Costs(assets)
    saved = {m: store.load_predictions(m) for m in registry}
    voters = {m: s for m, s in saved.items() if registry[m].get("kind") != "control"}
    derived = ensemble.derive(voters, costs)
    saved[ensemble.NAME] = derived
    results = {}
    for model in models(registry):
        preds = index_predictions(saved[model])
        for strategy, fn in STRATEGIES.items():
            result = fn(preds, prices, costs, settings.start_equity) if preds else None
            if result is None:
                result = Result([], [], [])
            _check(model, strategy, result)
            results[(model, strategy)] = result
    store.replace_predictions(ensemble.NAME, derived)
    done = {}
    for (model, strategy), result in results.items():
        store.write_account(model, strategy, result)
        if result.ledger:
            done[(model, strategy)] = len(result.equity)
    return done
```

- [ ] **Step 5: Implement the CLI command** (in `bench/cli.py`)

```python
def cmd_score(args, now):
    from bench.runner import cut_history
    from bench.scorer import score_store

    settings, assets = load_config(_assets_file())
    run_date = _run_date(args.run_date, now)
    prices = cut_history(load_prices(_data() / "prices", assets), run_date)
    modes = ("live", "backtest") if args.mode == "all" else (args.mode,)
    for mode in modes:
        done = score_store(Store(_data() / mode), prices, assets, settings, registry.REGISTRY)
        print(json.dumps({"mode": mode, "accounts": len(done), "settled_days": sum(done.values())}))
    return 0
```

Register it in `main`:

```python
    s = sub.add_parser("score")
    s.add_argument("--mode", choices=["live", "backtest", "all"], default="all")
    s.add_argument("--run-date")
```

and add `"score": cmd_score` to the `commands` dict.

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_scorer.py tests/test_cli.py tests/test_store.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add bench/store.py bench/scorer.py bench/cli.py tests/test_scorer.py tests/test_cli.py tests/test_store.py
git commit -m "feat: account storage, the scorer and the score command"
```

---

### Task 8: Runner predicts only; aggregate reads accounts; V1 broker removed

**Files:**
- Modify: `bench/runner.py`, `bench/aggregate.py`, `bench/config.py`, `bench/store.py`, `assets.yaml`, `site/lib.js`, `site/lib.test.js`, `tests/test_runner.py`, `tests/test_aggregate.py`, `tests/test_config.py`, `tests/test_store.py`, `tests/helpers.py`
- Delete: `bench/broker.py`, `tests/test_broker.py`

**Interfaces:**
- Consumes: `Store.load_account`, `Store.load_positions`, `scorer.score_store`, `scorer.models`, `STRATEGIES`, `ensemble.NAME`, `ensemble.LABEL`.
- Produces:
  - `run_estimator_day(store, estimator, prices, run_date, settings, now=None, assets=None)` no longer settles. Signature unchanged.
  - `Settings` loses `cost_round_trip` and `trade_threshold`; `assets.yaml` settings lose them too.
  - `Store` loses `load_equity`, `load_ledger`, `append_equity`, `append_ledger`, `EQUITY_COLS`, `LEDGER_COLS`.
  - `summary.json` keeps every existing key with the same shape, now computed from the `one_day` accounts, and gains: `strategies` (list of names), `modes[mode].accounts[strategy][model]` (a row, plus `groups`), and the ensemble in `estimators` with `kind: "derived"`. `modes[mode].hold` becomes the equity series of `control_always_long` under `hold`.
  - Per-model detail JSON gains `modes[mode].accounts[strategy] = {"stats", "equity", "positions"}`.
  - `tests.helpers.score(store, prices, assets=None)`: test helper that scores a store with the real registry.

- [ ] **Step 1: Add the test helper** (`tests/helpers.py`, append)

```python
def score(store, prices, assets=None, registry=None):
    """Score a test store the way the daily run does. Assets default to one flat-cost stock per price series."""
    from bench.config import Asset, Settings
    from bench.scorer import score_store
    from estimators.registry import REGISTRY

    assets = assets or [Asset(s, "stock", 5, 0.001, 0.0) for s in prices]
    return score_store(store, prices, assets, Settings(), registry or REGISTRY)
```

- [ ] **Step 2: Rewrite the tests that used the broker**

- `tests/test_runner.py`: lines that assert `st.load_equity("spy")` after `run_estimator_day` (two tests, around lines 152 and 177) test settlement inside the runner, which no longer exists. In each, after the runner call add `from tests.helpers import score` and `score(st, prices, registry={"spy": {"kind": "ml"}})`, then assert on `st.load_account("spy", "one_day")[0]` instead of `st.load_equity("spy")`. The expected values (10190.0) are unchanged because the helper uses a flat 0.1% cost. Add this test:

```python
def test_runner_no_longer_settles(tmp_path):
    st = Store(tmp_path)
    prices = {"SPY": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102)])}
    run_estimator_day(st, Always(), prices, "2026-01-06", Settings())
    run_estimator_day(st, Always(), prices, "2026-01-07", Settings())
    assert not (tmp_path / "accounts").exists()
    assert not (tmp_path / "estimators" / "always" / "equity.csv").exists()
```

  Use the file's existing fake estimator class in place of `Always()` (the file defines one that always predicts a gain; reuse it and its name).
- `tests/test_aggregate.py`: every `settle_estimator(st, n, prices, S)` loop becomes one `score(st, prices)` call after the predictions are saved (import `score` from `tests.helpers`; delete the `bench.broker` import). Assertions on balances stay valid because the helper's cost is the old flat 0.1%. Where a test seeds `control_random` and other registry names, nothing else changes.
- `tests/test_verify_data.py`: same replacement; Task 9 updates the checker itself, so mark any test that fails only because the checker still reads V1 files with `@pytest.mark.xfail(reason="Task 9 moves the checker to accounts", strict=True)` and list them in your report.
- `tests/test_store.py`: delete the tests of `load_equity` / `append_equity`; the account tests from Task 7 cover storage.
- `tests/test_config.py`: delete the assertion `settings.cost_round_trip == 0.001`; add:

```python
def test_cost_settings_are_gone():
    import pytest
    from bench.config import Settings
    assert not hasattr(Settings(), "cost_round_trip") and not hasattr(Settings(), "trade_threshold")
```

- Delete `tests/test_broker.py` (its cases are covered by `tests/test_strategy_daily.py`).

Add to `tests/test_aggregate.py`:

```python
def test_summary_has_strategies_accounts_groups_and_the_ensemble(tmp_path):
    from bench.aggregate import build_all
    from bench.config import Asset, Settings
    from bench.store import Store
    from estimators.registry import REGISTRY
    import json

    assets = [Asset("AAA", "stock", 5, 0.001, 0.0), Asset("BBB", "crypto", 5, 0.001, 0.0)]
    px = {
        "AAA": candles([("2026-01-05", 100, 100, 100, 100), ("2026-01-06", 100, 103, 99, 102), ("2026-01-07", 102, 104, 101, 103)]),
        "BBB": candles([("2026-01-05", 10, 10, 10, 10), ("2026-01-06", 10, 11, 9, 9), ("2026-01-07", 9, 9, 9, 9)]),
    }
    st = Store(tmp_path / "data" / "live")
    for n in REGISTRY:
        st.save_prediction(n, "2026-01-06", {
            "schema_version": 1, "estimator": n, "run_date": "2026-01-06", "created_at": None,
            "predictions": {s: {"asof": "2026-01-05", "expected_return": 0.01, "confidence": None, "path": None} for s in px},
        })
    score(st, px, assets)
    Store(tmp_path / "data" / "backtest")
    out = tmp_path / "site"
    build_all(tmp_path / "data", out, px, Settings(), assets, "2026-01-08", generated_at="2026-01-08T00:00:00Z")
    s = json.loads((out / "summary.json").read_text())
    assert s["strategies"] == ["one_day", "one_day_short", "hold", "top_picks", "weekly"]
    assert s["estimators"][-1] == {"name": "ensemble", "label": "Ensemble (majority vote)", "kind": "derived", "backfill_stride": 1}
    live = s["modes"]["live"]
    assert set(live["rows"]) == set(REGISTRY) | {"ensemble"}
    row = live["accounts"]["one_day"]["analog"]
    assert row["groups"]["stock"]["trades"] == 1 and row["groups"]["crypto"]["trades"] == 1
    assert row["groups"]["stock"]["net_sum"] > 0 > row["groups"]["crypto"]["net_sum"]
    assert "weekly" not in live["accounts"] or "analog" not in live["accounts"]["weekly"]
    assert live["hold"] and live["hold"][0][0] == "2026-01-06"  # always-long under the hold rule
    d = json.loads((out / "estimators" / "analog.json").read_text())
    assert set(d["modes"]["live"]["accounts"]) >= {"one_day", "hold"}
    assert d["modes"]["live"]["accounts"]["hold"]["positions"][0]["asset"] in ("AAA", "BBB")
    assert json.loads((out / "estimators" / "ensemble.json").read_text())["name"] == "ensemble"


def test_missing_accounts_are_skipped(tmp_path):
    from bench.aggregate import build_all
    from bench.config import Settings
    from bench.store import Store
    import json

    Store(tmp_path / "data" / "live")
    Store(tmp_path / "data" / "backtest")
    out = tmp_path / "site"
    build_all(tmp_path / "data", out, {}, Settings(), [], "2026-01-08", generated_at="2026-01-08T00:00:00Z")
    text = (out / "summary.json").read_text()
    s = json.loads(text)
    assert "NaN" not in text and "Infinity" not in text
    assert s["modes"]["live"]["accounts"] == {} and s["modes"]["live"]["hold"] == []
    assert s["modes"]["live"]["rows"]["analog"]["balance"] == 10000.0
```

- [ ] **Step 3: Run to verify the new tests fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_aggregate.py tests/test_runner.py`
Expected: FAIL (`KeyError: 'strategies'`, and the runner still settles).

- [ ] **Step 4: Implement**

`bench/runner.py`: delete `from bench.broker import settle_estimator` and the line `settle_estimator(store, name, history, settings)`. Change the docstring's first line to `"""Predict for one run date. Used by live runs and backfill. Scoring is a separate step (bench.scorer)."""`.

`bench/config.py`: delete `cost_round_trip` and `trade_threshold` from `Settings`. `assets.yaml`: delete those two lines from `settings`.

`bench/store.py`: delete `EQUITY_COLS`, `LEDGER_COLS`, `load_equity`, `load_ledger`, `append_equity`, `append_ledger`, `_load`, `_append`.

Delete `bench/broker.py`.

`bench/aggregate.py`, replace `_hold_curve`, `_mode_block` and `build_all` and add the helpers (keep `_records`, `_default`, `_status_for`, `_ticker`, `_skipped_stale`, `_row`, `_detail` as they are, except the two edits noted):

```python
from bench import ensemble
from bench.scorer import models as all_models
from bench.strategies import STRATEGIES

MAIN = "one_day"
CONTROL_RANDOM = "control_random"
CONTROL_LONG = "control_always_long"


def _series(eq):
    return [[d, round(float(e), 2)] for d, e in zip(eq["date"], eq["equity"])]


def _groups(led):
    """Per asset category: fee-paying trades, summed weighted net return, 1-day hit rate."""
    out = {}
    if led.empty:
        return out
    fee = led[led["action"].isin(["day", "open", "close"]) & (led["traded"] == 1)]
    for group, g in led.groupby("group"):
        out[group] = {
            "trades": int((fee["group"] == group).sum()),
            "net_sum": float((g["net_ret"] * g["weight"]).sum()),
            "hit_rate": scoring.hit_rate(g["hit"].dropna().tolist()),
        }
    return out


def _runs(store, name, run_date):
    """The ensemble is derived, so it has no run log: it ran if it has predictions for the run date."""
    if name != ensemble.NAME:
        return store.load_runs(name)
    return [{"run_date": run_date, "status": "ok"}] if run_date in store.load_predictions(name) else []


def _mode_block(data_dir, mode, prices, settings, run_date):
    store = Store(Path(data_dir) / mode)
    names = all_models(REGISTRY)
    accts = {(n, s): store.load_account(n, s) for n in names for s in STRATEGIES}
    runs = {n: _runs(store, n, run_date) for n in names}
    eqs = {n: accts[(n, MAIN)][0] for n in names}
    leds = {n: accts[(n, MAIN)][1] for n in names}
    dates = sorted({d for eq in eqs.values() for d in eq["date"]})

    def rand(strategy):
        eq = accts[(CONTROL_RANDOM, strategy)][0]
        return dict(zip(eq["date"], eq["day_return"]))

    rows, pnl, hit, equity = {}, {}, {}, {}
    for n in names:
        rows[n] = _row(eqs[n], leds[n], runs[n], settings, rand(MAIN), run_date)
        by_date = dict(zip(eqs[n]["date"], eqs[n]["day_return"]))
        pnl[n] = [by_date.get(d) for d in dates]
        scored = leds[n].dropna(subset=["hit"])
        hits = {} if scored.empty else scored.groupby("date")["hit"].mean().to_dict()
        hit[n] = [hits.get(d) for d in dates]
        equity[n] = _series(eqs[n])
    accounts, extra = {}, {}
    for s in STRATEGIES:
        for n in names:
            eq, led = accts[(n, s)]
            if eq.empty:
                continue
            row = _row(eq, led, runs[n], settings, rand(s), run_date)
            row["groups"] = _groups(led)
            row["hit_rate_5d"] = scoring.hit_rate(led["hit5"].dropna().tolist())
            accounts.setdefault(s, {})[n] = row
            extra[(n, s)] = {"stats": row, "equity": _series(eq), "positions": store.load_positions(n, s)}
    block = {
        "dates": dates, "rows": rows, "pnl": pnl, "hit": hit, "equity": equity,
        "hold": _series(accts[(CONTROL_LONG, "hold")][0]),
        "accounts": accounts,
    }
    return block, eqs, leds, extra


def build_all(data_dir, out_dir, prices, settings, assets, run_date, generated_at=None):
    out = Path(out_dir)
    (out / "estimators").mkdir(parents=True, exist_ok=True)
    meta = [
        {"name": n, "backfill_stride": 1, **{k: v for k, v in m.items() if k not in PUBLIC_META_SKIP}}
        for n, m in REGISTRY.items()
    ]
    meta.append({"name": ensemble.NAME, "label": ensemble.LABEL, "kind": "derived", "backfill_stride": 1})
    meta_by_name = {m["name"]: m for m in meta}
    names = [m["name"] for m in meta]
    details = {
        n: {"schema_version": SCHEMA_VERSION, "name": n, "meta": meta_by_name[n], "modes": {}}
        for n in names
    }
    modes = {}
    for mode in ("live", "backtest"):
        block, eqs, leds, extra = _mode_block(data_dir, mode, prices, settings, run_date)
        modes[mode] = block
        for n in names:
            d = _detail(eqs[n], leds[n], block["rows"][n])
            d["accounts"] = {s: extra[(n, s)] for s in STRATEGIES if (n, s) in extra}
            details[n]["modes"][mode] = d
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_date": run_date,
        "stale_assets": stale_assets(prices, assets, run_date),
        "estimators": meta,
        "strategies": list(STRATEGIES),
        "modes": modes,
        "ticker": _ticker(prices, assets),
    }
    (out / "summary.json").write_text(json.dumps(summary, default=_default), encoding="utf-8")
    for n, d in details.items():
        (out / "estimators" / f"{n}.json").write_text(json.dumps(d, default=_default), encoding="utf-8")
```

Two edits inside the kept functions, because the account ledger's date column is `date`, not `settle_date`:
- `_detail`: `led.groupby("settle_date")` becomes `led.groupby("date")`, and `g.drop(columns=["settle_date"])` becomes `g.drop(columns=["date"])`.
- `_row`: unchanged (it reads `hit`, `expected_return`, `n_traded`, which all still exist).

Remove `_hold_curve` and the now-unused `math` import only if nothing else uses it (`_ticker` does; keep it).

`site/lib.js`: `export const HOLD_LABEL = "Buy and hold, fees paid (always long under the hold rule)";`. Update the test in `site/lib.test.js` that asserts the old label text to assert the new one.

- [ ] **Step 5: Run all tests**

Run: `.venv/Scripts/python -m pytest -q` and `node --test site/lib.test.js`
Expected: all pass, except the tests you marked `xfail` in `tests/test_verify_data.py`. `grep -rn "settle_estimator\|load_equity\|append_ledger\|cost_round_trip\b.*settings\|trade_threshold" bench scripts tests estimators` must show no remaining use outside `scripts/verify_data.py` (Task 9).

- [ ] **Step 6: Commit**

```bash
git add -A bench tests site assets.yaml
git commit -m "feat: runner predicts only, aggregate reads accounts, V1 broker removed"
```

---

### Task 9: Checker, migration, workflows, rescored data and docs

**Files:**
- Create: `scripts/migrate_v2.py`, `tests/test_migrate_v2.py`
- Modify: `scripts/verify_data.py`, `tests/test_verify_data.py`, `bench/store.py` (`SCHEMA_VERSION = 2`), `bench/ensemble.py` (import the constant), `.github/workflows/daily.yml`, `.github/workflows/backfill.yml`, `tests/test_workflows.py`, `README.md`, `docs/data-repairs.md`, `data/` (migrated and rescored)

**Interfaces:**
- Consumes: everything above.
- Produces: `scripts/migrate_v2.py` with `migrate(data_dir) -> list[str]` (what it did); `check()` in `scripts/verify_data.py` covering accounts; workflows that score before verifying.

- [ ] **Step 1: Write the failing tests**

`tests/test_migrate_v2.py`:

```python
from scripts.migrate_v2 import migrate


def test_migrate_bumps_schema_and_removes_v1_ledgers(tmp_path):
    for mode in ("live", "backtest"):
        d = tmp_path / mode / "estimators" / "m1"
        (d / "predictions").mkdir(parents=True)
        (d / "predictions" / "2026-01-06.json").write_text("{}", encoding="utf-8")
        (d / "equity.csv").write_text("x", encoding="utf-8")
        (d / "ledger.csv").write_text("x", encoding="utf-8")
        (d / "runs.jsonl").write_text("{}\n", encoding="utf-8")
        (tmp_path / mode / "SCHEMA").write_text("1\n", encoding="utf-8")
    done = migrate(tmp_path)
    for mode in ("live", "backtest"):
        d = tmp_path / mode / "estimators" / "m1"
        assert (tmp_path / mode / "SCHEMA").read_text().strip() == "2"
        assert not (d / "equity.csv").exists() and not (d / "ledger.csv").exists()
        assert (d / "predictions" / "2026-01-06.json").exists() and (d / "runs.jsonl").exists()
    assert any("equity.csv" in line for line in done)
    assert migrate(tmp_path) == []  # running it again changes nothing


def test_migrate_refuses_an_unknown_schema(tmp_path):
    import pytest
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "SCHEMA").write_text("7\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="schema 7"):
        migrate(tmp_path)
```

In `tests/test_verify_data.py`: remove the `xfail` marks from Task 8, and add (build the store with `score` from `tests.helpers`, as the other tests in the file now do):

```python
def test_account_equity_must_compound(tmp_path):
    data = _good_data(tmp_path)  # the file's existing builder of a passing data folder; rename to match
    p = data / "live" / "accounts" / "e" / "one_day" / "equity.csv"
    text = p.read_text().splitlines()
    cells = text[1].split(",")
    cells[1] = "12345.0"
    text[1] = ",".join(cells)
    p.write_text("\n".join(text) + "\n")
    assert any("does not compound" in x for x in check(data, _assets_file(tmp_path)))


def test_one_day_ledger_must_match_the_candle(tmp_path):
    data = _good_data(tmp_path)
    p = data / "live" / "accounts" / "e" / "one_day" / "ledger.csv"
    p.write_text(p.read_text().replace(",100.0,", ",101.0,", 1))
    assert any("does not match the cached candle" in x for x in check(data, _assets_file(tmp_path)))


def test_crypto_prediction_must_be_asof_the_day_before_the_run(tmp_path):
    data = _good_data(tmp_path, crypto_asof="2026-01-03", run_date="2026-01-06")
    assert any("crypto" in x and "asof" in x for x in check(data, _assets_file(tmp_path)))
```

Adapt `_good_data` / `_assets_file` to the helper names the file already uses; if the file builds its data inline, extract one builder that takes `crypto_asof` and `run_date` keyword arguments and writes an assets file containing one stock and one crypto asset.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest -q tests/test_migrate_v2.py tests/test_verify_data.py`
Expected: FAIL (`ModuleNotFoundError: scripts.migrate_v2`; checker still reads V1 files).

- [ ] **Step 3: Implement the migration**

`scripts/migrate_v2.py`:

```python
"""One-off: store schema 1 -> 2. V1 kept one ledger per estimator; V2 keeps accounts per strategy.

Predictions and run logs are untouched. Run `python -m bench.cli score` afterwards to rebuild accounts.
"""
import sys
from pathlib import Path


def migrate(data_dir="data"):
    done = []
    for mode in ("live", "backtest"):
        root = Path(data_dir) / mode
        marker = root / "SCHEMA"
        if not marker.exists():
            continue
        found = int(marker.read_text().strip())
        if found == 2:
            continue
        if found != 1:
            raise RuntimeError(f"{root} has schema {found}; this script only migrates 1 to 2")
        for name in ("equity.csv", "ledger.csv"):
            for f in sorted((root / "estimators").glob(f"*/{name}")) if (root / "estimators").exists() else []:
                f.unlink()
                done.append(f"removed {f.as_posix()}")
        marker.write_text("2\n")
        done.append(f"{marker.as_posix()}: 1 -> 2")
    return done


if __name__ == "__main__":
    for line in migrate(sys.argv[1] if len(sys.argv) > 1 else "data"):
        print(line)
```

`bench/store.py`: `SCHEMA_VERSION = 2`. `bench/ensemble.py`: replace its own `SCHEMA_VERSION = 2` with `from bench.store import SCHEMA_VERSION` only if that creates no import cycle (`bench.store` imports `bench.strategies.common`, not `bench.ensemble`, so it does not). Update any test that writes `"schema_version": 1` into a SCHEMA marker file; prediction payloads carrying `schema_version: 1` are data and stay valid.

- [ ] **Step 4: Implement the checker**

In `scripts/verify_data.py`, replace the per-estimator equity and ledger blocks (everything from `eq = store.load_equity(name)` to the end of the loop body) with a predictions check plus an accounts loop:

```python
ACCOUNT_NUMERIC = ["entry", "exit", "expected_return", "net_ret", "weight", "cost", "actual_cc"]
```

```python
        crypto = {a.symbol for a in assets if a.group == "crypto"}
        for name in sorted(p.name for p in (root / "estimators").iterdir() if p.is_dir()):
            where = f"{mode}/{name}"
            for run_date, payload in store.load_predictions(name).items():
                day_before = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
                for asset, p in payload["predictions"].items():
                    if not p["asof"] < run_date:
                        problems.append(f"{where}/{run_date}/{asset}: asof {p['asof']} is not before the run date")
                    elif asset in crypto and p["asof"] != day_before:
                        problems.append(f"{where}/{run_date}/{asset}: crypto asof {p['asof']} is not the day before the run (retroactive prediction)")
        acct_root = root / "accounts"
        for model_dir in sorted(p for p in acct_root.iterdir() if p.is_dir()) if acct_root.exists() else []:
            for strat_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
                where = f"{mode}/{model_dir.name}/{strat_dir.name}"
                eq, led = store.load_account(model_dir.name, strat_dir.name)
                if eq.empty or led.empty:
                    problems.append(f"{where}: account files are empty")
                    continue
                if not _finite(eq, list(eq.columns.drop("date"))):
                    problems.append(f"{where}: equity.csv has missing or non-finite values")
                    continue
                if not _finite(led, ACCOUNT_NUMERIC):
                    problems.append(f"{where}: ledger.csv has missing or non-finite values")
                    continue
                if eq["date"].duplicated().any() or not eq["date"].is_monotonic_increasing:
                    problems.append(f"{where}: settled dates are not unique and increasing")
                expected = settings.start_equity * (1 + eq["day_return"]).cumprod()
                if (expected - eq["equity"]).abs().max() > 1e-6:
                    problems.append(f"{where}: equity does not compound from day returns")
                per_day = (led["net_ret"] * led["weight"]).groupby(led["date"]).sum()
                want = (per_day / eq.set_index("date")["n_universe"]).clip(lower=-1.0)
                got = eq.set_index("date")["day_return"]
                if set(per_day.index) != set(got.index) or (want - got).abs().max() > 1e-9:
                    problems.append(f"{where}: day returns do not follow from the ledger")
                if strat_dir.name in ("one_day", "one_day_short", "top_picks"):
                    m = led.merge(refs, on=["asset", "date"], how="left", suffixes=("", "_c"))
                    bad = m["open"].isna() | ((m["open"] - m["entry"]).abs() > 1e-9) | ((m["close"] - m["exit"]).abs() > 1e-9)
                    for r in m[bad].itertuples():
                        problems.append(f"{where}: ledger row {r.asset} {r.date} does not match the cached candle (entry/exit vs data/prices open/close; prices were re-based or the candle was incomplete)")
```

Build `refs` once per `check()` call, before the mode loop (it was built per estimator before):

```python
    frames = [df[["date", "open", "close"]].assign(asset=sym) for sym, df in prices.items() if df is not None and len(df)]
    refs = pd.concat(frames).drop_duplicates(["asset", "date"]) if frames else pd.DataFrame(columns=["date", "open", "close", "asset"])
```

Add `from datetime import date, timedelta` at the top. The crypto as-of rule applies to every model's predictions, the ensemble included.

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest -q tests/test_migrate_v2.py tests/test_verify_data.py`
Expected: all pass, none xfailed.

- [ ] **Step 6: Workflows**

`.github/workflows/daily.yml`, in the `aggregate` job, insert a step between "Merge estimator results" and "Verify data":

```yaml
      - name: Score accounts
        env:
          RUN_DATE: ${{ needs.fetch.outputs.run_date }}
        run: python -m bench.cli score --mode all --run-date "$RUN_DATE"
```

`.github/workflows/backfill.yml`, in the `commit` job, insert between its merge step and its verify step:

```yaml
      - name: Score accounts
        run: python -m bench.cli score --mode backtest
```

The backfill commit step already runs `git add data/backtest`, which now includes `data/backtest/accounts` and the derived `data/backtest/estimators/ensemble`. The daily commit step runs `git add data`. No other change.

Add to `tests/test_workflows.py`:

```python
def test_accounts_are_scored_before_they_are_verified():
    for name, job in (("daily.yml", "aggregate"), ("backfill.yml", "commit")):
        _, wf = load(name)
        runs = [s.get("run", "") for s in wf["jobs"][job]["steps"]]
        score = next(i for i, r in enumerate(runs) if "bench.cli score" in r)
        verify = next(i for i, r in enumerate(runs) if "verify_data.py" in r)
        commit = next(i for i, r in enumerate(runs) if "git commit" in r)
        assert score < verify < commit, name
    _, bf = load("backfill.yml")
    assert any("score --mode backtest" in s.get("run", "") for s in bf["jobs"]["commit"]["steps"])
```

(`load` is the helper the file already uses to return `(text, parsed_yaml)`; match its actual name and return shape.) The existing test that forbids `${{` inside `run:` scripts must still pass: `RUN_DATE` goes through `env`, as shown.

- [ ] **Step 7: Migrate and rescore the repo's data**

```bash
.venv/Scripts/python scripts/migrate_v2.py data
.venv/Scripts/python -m bench.cli score --mode all
.venv/Scripts/python scripts/verify_data.py data
```

Expected: the migration lists the removed V1 files and `1 -> 2` for both stores; `score` prints one JSON line per mode (backtest: about 50 accounts, live: 0 settled days); verify prints `data checks passed`. If verify reports crypto as-of problems in `data/backtest`, stop and report them: do not edit predictions.

Then build the site data into a scratch folder and confirm the current dashboard still works:

```bash
BENCH_SITE=/tmp/v2site .venv/Scripts/python -m bench.cli aggregate
```

Check with a short script that `summary.json` parses with `json.loads(text, parse_constant=...)` rejecting NaN, that `modes.backtest.accounts` has all five strategies, and print each strategy's best and worst balance for the report.

- [ ] **Step 8: Docs**

- `README.md`: replace the cost paragraph (flat 0.1%) with the per-group table from the spec section 5, the list of what is not modelled (broker commissions and currency conversion with the XTB figures, slippage), and the statement that crypto shorting is a simplification. Add a short "Account types" section naming the five rules in one line each, the ensemble, and buy-and-hold with fees. State that the luck check compares each account with the random control under the same rule. Update the "Roadmap (V2)" list: mark items 1 and 3 (hold accounts, shorting) as built in part 1 and note that their dashboard views arrive in part 2.
- `docs/data-repairs.md`: add an entry dated today: store schema 1 to 2, V1 ledgers removed, all accounts rescored under per-asset costs, with the command lines used.
- Update the spec's section 4.5 wording only if your reading in Task 5 differed; otherwise leave the spec alone.

- [ ] **Step 9: Run everything**

Run: `.venv/Scripts/python -m pytest -q`, `node --test site/lib.test.js`, `.venv/Scripts/python scripts/verify_data.py data`
Expected: all pass; `data checks passed`.

- [ ] **Step 10: Commit** (two commits: code and docs, then data)

```bash
git add scripts bench tests .github README.md docs
git commit -m "feat: account checks, schema 2 migration and scoring in the workflows"
git add data
git commit -m "data: migrate to schema 2 and rescore every account under per-asset costs"
```

---

## Self-review notes

- Spec 3 (structure, storage): Tasks 2, 7, 8. Spec 4.1 to 4.5: Tasks 2 to 5. Spec 4.6: Task 6 and the scorer in Task 7. Spec 4.7: `control_always_long` under `hold` (Task 8 `hold` series; README in Task 9). Spec 5: Task 1, README in Task 9. Spec 6: baseline per strategy and category split in Task 8; the Bonferroni threshold is a dashboard calculation and stays as is until part 2 shows the other strategies (the summary now carries what part 2 needs). Spec 7: Task 9. Spec 8: missing model and missing prediction (Task 4), no session (Tasks 4 and 5), non-finite (Task 7), equity floor (`finish`, Task 2), late candle per asset (covered by the full recompute: an account is rebuilt from all candles each run, so a candle that arrives late is settled on the next run). Spec 9: tests in every task; the V1 reproduction test in Task 2.
- Reading of spec 4.5 fixed in Task 5: slots are per asset, a fifth of the asset's share each, so exposure never exceeds 100%.
- Spec 8 "stale asset: held position is kept": an asset with no new candle has no session that day, so `hold` writes no row and carries it (Task 4 `test_position_carried_over_days_without_a_candle`).
