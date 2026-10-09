# Data repairs

One-off corrections to committed data. The price cache is append-only and live results are never
edited in normal operation, so every manual change is listed here with its reason.

## 2026-10-08: retroactive crypto predictions removed from the live set

**Defect.** The scheduled run of 2026-10-08 (started 06:22 UTC) predicted BTC-USD, ETH-USD and
SOL-USD with `asof` 2026-10-06, because the fetch at 06:22 had stored no 2026-10-07 crypto candle
(it printed `BTC-USD: ok`; the bar only appeared in the 14:27 manual run). The 2026-10-07 crypto
session was therefore already complete when that "prediction" was made. The models never saw
2026-10-07 data, but the core promise (a prediction is committed before the session it trades) was
broken. The 14:27 manual run then settled those three trades into the ledger and equity files.

**Removed** (all 11 estimators under `data/live/estimators/`):

- `ledger.csv` and `equity.csv`: deleted. Their only rows were dated 2026-10-07 (the three crypto
  trades and the day they produced), so the files were removed and the live set restarts with no
  settled days.
- `predictions/2026-10-08.json`: the BTC-USD, ETH-USD and SOL-USD entries (`asof` 2026-10-06, not
  the expected 2026-10-07). The 18 stock, ETF and commodity predictions are untouched.
- Not touched: `runs.jsonl` (the audit trail keeps the original `ok` / 21 predictions record and
  the 14:27 `skipped_late` record) and `data/prices`.

**Effect on the next run (2026-10-09).** The broker derives `last_done` from `equity.csv`; with the
file gone it is empty, so nothing is skipped. The 18 remaining predictions (asof 2026-10-07)
settle against the 2026-10-08 candles, and crypto gets fresh predictions with asof 2026-10-08.

**Prevention.** `assets.yaml` sets crypto `max_gap_days: 0` and the runner skips (and records as
`skipped_stale`) any asset whose newest candle at or before the cutoff is older than its
`max_gap_days`. `bench.cli fetch` now prints `WARNING: <asset> newest candle <date> is older than
expected <date>` plus a `::warning::` annotation. The dashboard and the notification report stale
assets.

**How.** A one-off script edited the files (asserting the expected rows first); `verify_data.py`
and a scratch `aggregate` confirmed 0 settled live days and consistent data.

## 2026-10-09: store schema 1 to 2, V1 ledgers removed, all accounts rescored

**Change.** V2 part 1 replaces the single per-estimator account with five accounts per model under
per-asset costs. The store schema marker in `data/live` and `data/backtest` goes from 1 to 2.

**Removed.** `estimators/<name>/ledger.csv` and `equity.csv` in both stores (the V1 flat-0.1% accounts).
Predictions, `runs.jsonl` and `data/prices` are untouched.

**Added.** `accounts/<model>/<strategy>/` (ledger, equity, positions) for every model and the derived
`ensemble`, rebuilt from the stored predictions. The live store has no settled day, so its accounts are empty.

**Commands.**

```sh
python scripts/migrate_v2.py data
python -m bench.cli score --mode all
python scripts/verify_data.py data
```

