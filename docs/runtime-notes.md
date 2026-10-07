# Runtime notes

Measured on the first cloud runs (2026-10-06). The repo is public, so Actions minutes are free; the numbers are recorded to see how much headroom the schedule has.

## Backfill (365 days, 6 estimators, one job each)

| Job | Duration |
|---|---|
| fetch | ~35 s |
| backtest control_always_long | ~50 s |
| backtest control_random | ~55 s |
| backtest candle_rules | ~65 s |
| backtest analog | ~70 s |
| backtest control_persistence | ~70 s |
| backtest xgb_indicators | ~75 s |
| commit | ~35 s |

The longest job is about 75 s against the 340 minute job limit, so the cheap estimators have a huge margin. Heavy estimators (neural, retrained per day) must be measured before they join: see `backfill_stride`.

## Daily run (manual dispatch, 21:25 UTC)

| Job | Duration |
|---|---|
| fetch | ~26 s |
| predict (each of 6) | 20 to 35 s |
| aggregate | ~34 s |
| deploy | ~8 s |
| notify | ~20 s (no `NTFY_TOPIC` secret set yet, so it skipped quietly) |

Total about 4 runner minutes per day; longest single job about 35 s against the 45 minute `timeout-minutes`. Run outside the first 6 hours of the UTC day (the window was 6 hours then; it is now 11), so every estimator recorded `skipped_late`; that is the designed behaviour.

## Found by the first cloud run

The backfill `commit` job failed once: `git pull --rebase` refuses to run with unstaged changes, and the fetch step had refreshed `data/prices`, which a backfill deliberately does not commit. Fixed by discarding unstaged changes before the rebase (regression test in `tests/test_workflows.py`).

## First scheduled run

Created 2026-10-07 06:13:45 UTC against a 00:30 cron (about 5h43m late). The 6-hour window made every estimator `skipped_late`, so no live prediction was made for that day. The window was widened to 12 hours and then set to 11 hours (`LIVE_WINDOW_HOURS`), which ends at 11:00 UTC; the worst case (window, plus a predict job of up to 45 minutes, plus aggregate and commit of up to 20 minutes) still lands before the first US session opens at about 13:30 UTC, which 12 hours would not guarantee. Estimators only see candles dated before the run date, so a later start adds no look-ahead in data; the cost is that a crypto prediction can be committed up to 11 hours after that day's 00:00 UTC candle opens, which the dashboard footer and README state. That run's aggregate step also failed on the adjusted-price mismatch fixed earlier (commit 1649396).

## Still to measure

- The first scheduled 00:30 UTC run: how late GitHub starts it (the live window is now 11 hours; see "First scheduled run").
- Heavy estimators once they exist (Task 15).
- Do not run a backfill near 00:30 UTC: both workflows share the `bench-data` concurrency group, so a long backfill delays the daily run.

## Cloud backfill at stride 1, all 11 estimators (2026-10-07)

| Estimator | Job duration |
|---|---|
| controls, analog, xgb_indicators, candle_rules, statsforecast_auto, chronos, lstm | 1 to 6 min each (incremental when data already exists) |
| timesfm | ~26 min (from scratch, 365 days) |
| kronos | ~48 min (from scratch, 365 days) |

Both heavy jobs are far below the 340 minute limit; the earlier stride 3 / stride 2 settings were needless. A daily run with all 11 estimators takes about 3.5 minutes end to end (fetch ~26 s, slowest predict cell ~1 min, aggregate ~35 s, deploy ~10 s, notify ~20 s).
