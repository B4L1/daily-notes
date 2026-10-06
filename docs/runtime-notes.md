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

Total about 4 runner minutes per day; longest single job about 35 s against the 45 minute `timeout-minutes`. Run outside the first 6 hours of the UTC day, so every estimator recorded `skipped_late`; that is the designed behaviour.

## Found by the first cloud run

The backfill `commit` job failed once: `git pull --rebase` refuses to run with unstaged changes, and the fetch step had refreshed `data/prices`, which a backfill deliberately does not commit. Fixed by discarding unstaged changes before the rebase (regression test in `tests/test_workflows.py`).

## Still to measure

- The first scheduled 00:30 UTC run: how late GitHub starts it (the live window is 6 hours).
- Heavy estimators once they exist (Task 15).
- Do not run a backfill near 00:30 UTC: both workflows share the `bench-data` concurrency group, so a long backfill delays the daily run.
