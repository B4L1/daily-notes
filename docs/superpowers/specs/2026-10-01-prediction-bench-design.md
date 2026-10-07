# Prediction Bench — design

**Date:** 2026-10-01 · **Status:** draft for owner review · **Path:** architectural (new project)

## 1. Purpose and success criteria

Find out whether any of a set of candle/price prediction tools has real predictive skill, or only appears to. Each tool ("estimator") gets a simulated bank account and trades on its own predictions every day, on the same rules as every other estimator. The owner sees each estimator's work, day by day, and can compare them.

The project succeeds when:

1. It runs every day with no manual action and the owner gets a phone notification.
2. Every estimator and three control estimators are scored on identical rules.
3. The owner can open a page and see, per estimator, every past day: what it predicted, what happened, and what the paper account did.
4. The page says plainly when there is too little data to tell skill from luck, and compares every estimator against a random-guess control.
5. Adding a new estimator is one folder, not a rewrite.

**The owner's stated intent:** "see if any of them actually do anything, or if they just guess." The design optimises for an honest answer to that question, not for a flattering one.

## 2. Non-goals

- No real money, no broker connection, no order placement. Paper trading only.
- No investment advice. The page carries a short "experiment, not advice" note.
- No shorting and no leverage (see section 6).
- No intraday or multi-day holding in v1. Daily candles only.
- No accounts, logins or user input. The dashboard is read-only.
- No tuning of estimators to improve their score. A bench that edits models until they win measures the editing.

## 3. Assets

Default list, kept in an editable `assets.yaml` (about 21 assets):

- **Stocks and ETFs (15):** SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, XOM, WMT, JNJ, AMD
- **Crypto (3):** BTC-USD, ETH-USD, SOL-USD
- **Commodities via ETFs (3):** GLD, SLV, USO. ETFs were chosen over futures because they share the stock calendar and have no contract-roll gaps, which would appear as false price jumps.

Each asset carries its own calendar. Stocks have no candle on weekends and holidays. Crypto has a candle every day, closing at 00:00 UTC. An asset with no new completed candle on a given day is neither predicted nor settled that day.

## 4. Architecture

One public GitHub repo. GitHub Actions is the scheduler, the repo is the database, and GitHub Pages serves the dashboard.

```
assets.yaml                 editable asset list
bench/                      shared code: fetch, broker, scoring, controls, aggregate, notify
estimators/<name>/          predict.py + requirements.txt + README (what it is, source, licence)
data/
  prices/<asset>.csv        daily candle cache
  estimators/<name>/
    predictions/YYYY-MM-DD.json
    ledger.csv              one row per simulated trade
    equity.csv              one row per day
  meta/runs.jsonl           one record per run, per estimator: ok / failed / stale
site/                       static dashboard, built from data/
.github/workflows/
  daily.yml                 scheduled run
  backfill.yml              one-off manual run
```

**Daily flow** (cron at 00:30 UTC). This time is chosen so a prediction is always committed *before* the session it trades. At 00:30 UTC the previous US session has closed in both summer and winter time, the previous UTC day's crypto candle has just completed, and the next US session is still about 13 hours away. (An earlier draft ran at 22:30 UTC, which would commit crypto predictions after most of the day they trade had already happened.) The one remaining approximation: a crypto trade enters at the 00:00 UTC open and its prediction is committed up to 12 hours later (the live window is 12 hours after 00:00 UTC, because GitHub delayed the first scheduled run by 5h43m; it still ends before the first US session opens at about 13:30 UTC). Estimators only see candles dated before the run date, so the delay adds no look-ahead in data. This is documented on the dashboard.

1. **Fetch** the latest completed candles per asset.
2. **Settle** yesterday's saved predictions against the real outcome and update each account.
3. **Predict** tomorrow. One job per estimator runs in a matrix, in parallel, each in its own environment. A failing job does not stop the others.
4. **Aggregate** (runs even if some estimators failed): merge results, rebuild the site, commit the `data/` changes.
5. **Notify** through ntfy.

**Idempotency.** A run is keyed by date. Re-running the same day overwrites that day's files and never double-counts. A workflow concurrency group prevents two runs overlapping. GitHub's cron can start late, so nothing depends on the exact start time.

**Predictions are written before their outcome exists**, and the commit history is the audit trail. The harness gives an estimator only candles up to and including the prediction date. A test enforces this (section 11).

## 5. Estimators

Every estimator implements one function: given price history up to date *t* for one asset, return a prediction for the next session: direction, expected return, confidence, and, if it forecasts further ahead, the predicted path. Only the first day is traded in v1. The full path is saved so that path accuracy can be scored later without re-running anything.

**Lineup (first release):**

| Estimator | Kind | Notes |
|---|---|---|
| CandleEdge-style pattern matching | no training | Finds similar past candle structures and reports what followed. |
| big-data-stock-price-forecast idea | no training | Similar-sequence forecasting. |
| neural-candlestick | trained weekly | The repo describes itself as an experiment on whether candles are exploitable. |
| candlesticks_predictions (Transformer) | trained weekly | Its own README reports skeptical results, which is a useful prior. |
| Kronos | pretrained, inference only | Open-source foundation model for candlesticks. |
| TimesFM | pretrained, inference only | General time-series foundation model. |
| XGBoost on technical indicators | trained weekly | The common "ML on RSI/MACD" approach. |
| LSTM on technical indicators | trained weekly | As above. |
| Candlestick pattern rules | no training | Rules from `pandas-ta-classic` patterns. |

**Controls**, scored on identical rules: always-long (trades every asset every day, paying the same costs), random coin flip, "tomorrow equals today". A true buy-and-hold line (equal-weight, close to close, no costs) is drawn on the charts as a reference line, not as an account, because the daily open-to-close broker misses overnight gains and so is not comparable to holding.

**Source caveats.** The four repos named by the owner were not verified to install and run. For each, the first attempt is to wrap the original code. Where it is unusable as a library, the core idea is reimplemented and the estimator's tab says so and credits the source. Freqtrade is not an estimator. It is used only as a reference, and the bench has its own lightweight paper broker so every estimator is scored by the same code. The Kronos repository found during research looked like a fork, so the official source and its licence are confirmed before use.

**Training.** Cheap trained estimators (XGBoost) retrain from the truncated history on every run, which is the purest walk-forward and needs no saved state. Expensive neural estimators retrain weekly and use cached weights on other days. Weights live in a workflow cache, never in the repo.

## 6. Paper trading rules (identical for all estimators)

- Each account starts at $10,000 and is **continuous**: the full balance, gains and losses included, carries into the next day. There is no reset and no top-up.
- **Timing:** predictions are made after the close on day *t*. A trade enters at day *t+1* open and exits at day *t+1* close. The prediction never sees the price it trades at.
- **Allocation:** each day the account's current equity is split equally across the assets that have a session. Positions never carry overnight in v1, so equity compounds daily.
- **Long-only.** If the predicted return exceeds the cost threshold, the estimator buys. Otherwise it stays in cash for that asset.
- **Costs:** about 0.1% round trip (fee plus slippage), charged on every trade, configurable. A predicted move smaller than the cost means stay in cash.
- **Separate direction score.** Direction accuracy is scored independently of the account, including "down" calls. This credits correct drop predictions that a long-only account cannot profit from.

## 7. Scoring

Per estimator, computed from the saved files:

- Equity curve, daily return, total return, maximum drawdown, worst day.
- Direction hit rate overall and on "down" calls; hit rate per asset.
- Edge against the random control, and a luck indicator (bootstrap or permutation against random-control results).
- **"Too early to tell"** is shown until a configurable minimum of live trading days exists (default 60). Below that, the luck indicator is replaced by that message.

Scoring code is the one part where a wrong number invalidates everything, so it is tested against hand-calculated cases (section 11).

## 8. Backfill

A one-time manual workflow replays the past year day by day. For each past day every estimator sees only data before that day (walk-forward). Results are stored in the same format and clearly labelled **backtest**, separate from **live**.

- Self-trained estimators get an honest walk-forward replay.
- **Pretrained models (Kronos, TimesFM) were trained by their authors on data that very likely includes the past year.** Their backtest scores are labelled "may be optimistic" and can't be fixed. The live series is the real verdict.
- Backtest and live are separate accounts. The dashboard has a Live / Backtest switch, and each view has its own wallet strip, charts and heatmaps, so the two can never be read as one series.
- Because a regression model's predictions shrink towards zero, it may rarely beat the cost threshold and stay in cash most days. The leaderboard shows trades per day, and the trade threshold is a setting that defaults to the round-trip cost.

## 9. Dashboard

Static site, no build step, reading the committed JSON. Works on a phone, since the ntfy message opens it. **Visual direction: A, terminal** — dark, monospace, dense; chosen by the owner from three shown mockups.

**Overview**
- **Wallet strip (top of page):** one tile per estimator and control showing its current balance, today's change in dollars and percent, and a small sparkline. Balances are continuous: each account carries its full balance from day to day and never resets. Tiles are sorted by balance, so anyone "popping off" rises to the top.
- **Sanity flag:** a tile gets a "check this" badge if the account gains more than a set threshold (default +10% in one day or +50% in a week). Returns that large are far more likely to be a bug or a data leak than skill, so the bench asks for a look before anyone celebrates.
- Leaderboard: one row per estimator and control: account value, return, edge over random, hit rate, max drawdown, worst day, status badge (ok / failed today / stale).
- Equity curves for all accounts on one chart.
- Two heatmap grids, one row per estimator and one column per day: (1) daily paper-account return, (2) direction hit rate. Green and red, brighter for larger magnitude.

**One tab per estimator** (hash routes, so each is linkable)
- Header: what it is, where it came from, original code or our reimplementation, licence.
- Its own stats, equity curve, and both heatmaps as GitHub-style calendars.
- Day-by-day table, clickable: per asset, predicted vs actual, and the trade's profit or loss.
- Predicted path against the real one, for multi-day forecasters.
- Per-asset breakdown.

**States the book requires designing** (chapters 23–25): first-day empty page, "too early to tell", estimator failed today, stale data, a day with no sessions, a single data point.

**Colour and accessibility** (chapters 8 and 28): colour is never the only signal. Every heatmap cell and number carries a sign marker (▲/▼ or +/−) in its tooltip and table, and a one-click colour-blind palette (blue/orange) is included. Motion is minimal and respects `prefers-reduced-motion`.

## 10. Notifications

ntfy.sh. The topic name is a GitHub secret, never in the repo. The message is sent at low priority, because the run lands at about 03:00 local time and should not wake anyone. One message per day: day number, best and worst estimator return, how many beat the random control, and a link to the dashboard. A run with failures says which estimators failed. If the aggregate job itself fails, a failure message is sent.

## 11. Testing

- **Broker and scoring:** unit tests with hand-calculated cases (known prices in, known P&L, drawdown and hit rate out).
- **No look-ahead guard:** a test runs an estimator on history truncated at *t* and on full history, and asserts the prediction for *t* is identical.
- **Idempotency:** running a day twice yields the same files.
- **Failure handling:** a simulated estimator crash yields a "failed" record, no fabricated prediction, and the other estimators' results intact.
- **Schema:** every data file carries a `schema_version`; a loader test guards old files against format changes.
- Estimators themselves are not unit tested for accuracy. That is what the bench measures.

## 12. Failure handling

- Estimator job fails: recorded as `failed` for that day. The account stays in cash, which keeps it comparable. No prediction is invented.
- Price fetch fails for an asset: that asset is marked stale and skipped. Nothing is filled in from the previous day.
- Missed schedule: the next run detects the gap, fetches the missing candles, and settles in order. Predictions for days that were missed are not back-filled, because they would not have been made in time.

## 13. Rulebook applicability (Foundry, *The Book of Coding Secrets*)

Project kinds: `site` and `data-pipeline`.

**Declared capabilities:** `has-ui`, `has-routes`, `ships-client-bundle`, `is-deployed`, `has-third-party-deps`, `calls-external-apis`, `runs-background-jobs`, `has-persistent-state`, `costs-money-to-run`, `sends-push-notifications`.

**Applied chapters:** 1–5, 6–12, 14–19, 21, 23–25, 28–31, 34–37, 40, 43 and, for the push part only, 44.

**Waived, for personal use, deliberately and not silently:** 13 audio, 20 forms, 22 i18n, 26 and 41 auth, 27 destructive actions, 32 discovery and SEO, 33 legal and privacy, 42 review process, 44 email, 45–49.

Declared against the code at the end: any capability used but not declared is a finding (the book's capability-drift rule). The plan step reads each applied chapter before its implementation task.

## 14. Risks and open items

- **Price data source.** yfinance is unofficial and can break or be rate-limited. Per chapter 19, its terms, limits and a fallback source are recorded before code depends on it.
- **Upstream repos.** May not install, run on CPU within the free runners, or carry compatible licences. Verified per estimator before it enters the lineup. The public repo must respect each licence.
- **Runner time.** Kronos and TimesFM on CPU across about 21 assets need measuring. The public repo keeps Actions minutes free, but jobs still have a time limit.
- **Public repo.** Predictions and results are visible to anyone with the link. A plain repo name and empty description reduce casual discovery but are not privacy. Nothing secret is ever committed. A private repo plus Vercel is the fallback if the owner wants it.
- **Statistical honesty.** Even with 21 assets and several months, most estimators will be indistinguishable from luck. "Inconclusive" is a legitimate and expected outcome, and the dashboard reports it as one.
- **Survivorship and choice bias.** The asset list is fixed in advance and recorded. Changing it mid-run is marked on the charts.

## 15. Build order (for the plan)

1. Repo skeleton, asset config, data fetch and price cache.
2. Paper broker, scoring and the three controls, with their tests.
3. Estimator interface, the no-look-ahead guard, and the first two estimators end to end.
4. Daily workflow, aggregate job, idempotency, failure handling, ntfy.
5. Dashboard: overview, then the per-estimator tab.
6. Remaining estimators, one at a time, each verified before it joins.
7. Backfill workflow and the backtest/live separation.
8. Rulebook check-through and the capability-drift check.
