# Prediction bench

A paper-trading bench that asks one question: does any price-prediction tool have real skill, or does it only look that way? Each tool (an "estimator") gets a simulated $10,000 account and trades on its own predictions every day, under the same rules as every other estimator, next to three controls (always long, a random coin flip, "tomorrow equals today"). A page shows every day of every account.

**This is an experiment, not investment advice.** No real money is involved, there is no broker connection, and nothing here recommends buying or selling anything. The data is public daily prices.

An inconclusive result ("nothing beats the random control") is a legitimate and likely outcome, and the dashboard reports it as one.

## How a day works

A scheduled GitHub Actions workflow (`.github/workflows/daily.yml`) runs at 00:30 UTC every day. That time is chosen so a prediction is always committed before the session it trades.

1. **Fetch** the latest completed daily candles for about 21 assets (`assets.yaml`: 15 US stocks and ETFs, 3 crypto, 3 commodity ETFs). Source: `yfinance` (unofficial, see `docs/data-sources.md`).
2. **Predict** the next session. One job per estimator runs in parallel; a failing estimator is recorded as failed and the others carry on. Predicting only stores predictions; it does not settle anything.
3. **Score** every account from the stored predictions and the prices (`python -m bench.cli score --mode live`). Scoring is recomputed in full on every run, so a day whose candle arrives late is picked up on the next run.
4. **Aggregate** the results into static JSON, verify the data, commit it, and deploy the dashboard to GitHub Pages.
5. **Notify** through [ntfy](https://ntfy.sh): one low-priority message per day with the best and worst return, how many estimators beat the random control, and a link.

The trading rules are the same for every account: the full balance carries over from day to day (no reset) and a trade enters at a session's open. How a day's return is weighted depends on the account type. One-day accounts (`one_day`, `one_day_short`, `top_picks`) split the account equally across the assets that have a session that day. `hold` and `weekly` accounts give every asset in the universe an equal fixed share (an asset counts from its first candle), so they are never more than 100% invested: on a Saturday only crypto trades, and each crypto position still counts for its small fixed share, not for a larger one. Every account pays the real cost of the asset it trades, and a model trades an asset only when its predicted return is above that asset's own round-trip cost.

### Account types

Each model's stored predictions are scored under five rules, so every model has five accounts. Scoring is separate from predicting, so the whole backtest can be rescored in seconds (`python -m bench.cli score --mode backtest`) without re-running any model.

- `one_day`: long only; buy at the open and sell at the close when the expected return beats the cost.
- `one_day_short`: as `one_day`, and also shorts at the open and buys back at the close when the expected return is below minus the cost.
- `hold`: buy when the expected gain beats the cost, keep the position while the newest prediction is still above zero, sell at the next open otherwise; overnight moves are earned and fees are paid only when the position changes.
- `top_picks`: the 3 strongest calls of the day, traded as in `one_day`.
- `weekly`: for models with a 5-day path; one fifth of the account enters each day and is sold at the close of its fifth session.

Two more accounts are derived, not models: the **ensemble** (majority vote of the models; the controls do not vote) goes through the first four rules, and **buy-and-hold with fees** is the always-long control under `hold` (it buys every asset once, pays the entry cost once and holds). Buy-and-hold with fees is the honest baseline. The luck check compares each account with the random control under the same rule.

### Costs

Round trip means buy and sell, as a fraction of the position; entry and exit each pay half. Short borrow is charged per calendar day held (annual rate divided by 360). Figures live per asset in `assets.yaml`.

| Group | Assets | Round trip | Short borrow, per year | Basis |
|---|---|---|---|---|
| ETF | SPY, QQQ | 0.01% | 0.5% | Quoted spreads of 0.0032% (SPY) and 0.0041% (QQQ), rounded up; zero commission |
| Stock | 13 large US stocks | 0.05% | 0.5% | US equity spreads range 2 to 20 basis points with a median of 9; large caps sit at the low end; zero commission |
| Commodity | GLD, SLV, USO | 0.03% | 0.5% | GLD quoted spread 0.0065%; SLV and USO not found, assumed wider |
| Crypto | BTC, ETH, SOL | 0.25% | 10% | 0.1% taker fee per side at the cheapest major exchange, plus spread |

Unverified: the SLV and USO spreads (0.03% is an assumption); the stock figure is a judgement inside a published range, not a per-stock measurement; the crypto short cost is an assumption. Crypto fees depend heavily on the exchange (0.1% per side at Binance, 0.26% at Kraken's base tier, 0.40% to 1.20% at Coinbase Advanced for small accounts), so 0.25% is the cheap end. **Crypto shorting is a simplification:** real crypto shorts use derivatives with a funding rate that changes daily and can be negative.

Not modelled:

- Broker commissions and currency conversion. At XTB, real stocks and ETFs are commission-free up to 100,000 EUR of monthly turnover, then 0.2%; a $10,000 account trading every day passes that limit. XTB also charges 0.5% for currency conversion when the account currency differs from the asset's, which is 1% per round trip and would outweigh every other cost here. The bench assumes a USD account at a low-cost broker.
- Slippage beyond the spread, and market impact. At $10,000 they are negligible for these assets.

Sources: [ETF spreads, etf.com](https://www.etf.com/sections/news/why-trading-spreads-matter-etfs); [XTB fees](https://www.xtb.com/en/help-center/instruments/do-you-charge-commissions); [crypto fee comparison](https://www.spark.money/tools/crypto-exchange-fee-comparison); [borrow fees, Interactive Brokers](https://www.interactivebrokers.com/campus/traders-insight/securities/short-selling/the-risks-of-shorting-series-part-ii-borrow-fees/).

Two stated approximations:

- A crypto trade enters at the 00:00 UTC open, and its prediction is made up to 11 hours later (the cron fires at 00:30 UTC but GitHub can start it late; a run that starts after the 11-hour live window records `skipped_late`, so even the slowest accepted run commits before the US open at about 13:30 UTC), using only data from before that day.
- One-day accounts trade open to close, so they ignore overnight gaps. `hold` and `weekly` accounts keep positions overnight and earn the overnight moves. The dashed line on the charts is the always-long control under the hold rule, fees paid.

## Reading the dashboard

The dashboard is a static page (no login, no input). The ntfy message links to it; its address is `https://<owner>.github.io/<repo>/`.

- **Live / Backtest switch.** Live is the real record: each prediction was committed before its session. Live rows can be revised once: scoring is recomputed from predictions and prices on every run, so if a candle for a day arrives late (Yahoo's crypto candles have arrived a day late), that day's figures are recalculated on the next run. The predictions themselves are never changed. Backtest replays the past year day by day, with each day seeing only earlier data. The two are separate accounts with separate charts, and are never combined. Pretrained models may have seen the backtest period in training, so their backtest numbers may be optimistic; live is the real verdict.
- **Wallet strip.** One tile per account: balance, today's change, a small sparkline. Sorted by balance. A "check this" badge appears on a gain of more than 10% in a day or 50% in a week, because returns that large are more likely a bug or a data leak than skill.
- **Hold line.** The dashed grey line on the charts is buy and hold with fees: the always-long control under the hold rule. It buys every asset once, pays the entry cost once, and keeps the position, with each asset holding an equal fixed share.
- **Heatmaps.** One row per estimator, one column per day: (1) daily account return, (2) direction hit rate. Brighter means a bigger magnitude; green and red (or blue and orange, with the colour-blind palette button). Each cell also carries a sign marker in its tooltip.
- **Luck check.** For each estimator, a one-sided sign-flip permutation test on its daily return minus the random control's. "Unlikely luck" means p below the corrected threshold; "consistent with luck" means it cannot be told apart from guessing. Many estimators are tested at once, so a single p<0.05 is expected by chance: with N accounts tested, we use 0.05/N (Bonferroni; N is the number of non-control accounts shown, currently 9 with the ensemble, so about 0.0056). The threshold is shown next to every verdict.
- **"Too early to tell".** Shown in place of the luck check until an estimator has 60 live trading days (`min_live_days` in `assets.yaml`).
- **Ticker strip.** A scrolling LED-style strip at the top: each tracked asset's last close and its last completed day's change (close to close, raw prices), winners first, then losers. It pauses on hover, stands still (and scrolls by hand) if your system asks for reduced motion, and has a plain-text list for screen readers. Direction is also shown by the arrow and sign, not only the colour. Previous-day moves only, not advice. Data: the `ticker` list in `summary.json`.
- **Estimator tabs.** Each estimator has its own tab: where it came from, its licence, its stats, calendar heatmaps, a per-asset breakdown, and a day-by-day table with predicted vs actual for every asset.

## What the backtest says so far

Backtest over 365 settled days with the V2 costs and account rules. Final value of a 10,000 start, per model and account type:

| Model | One-day | One-day short | Hold | Top picks | Weekly |
|---|---|---|---|---|---|
| Analog candle matching | 8,840 | 7,593 | 10,475 | 9,334 | – |
| Candlestick pattern rules | 10,103 | 10,066 | 10,135 | 10,095 | – |
| Chronos-Bolt Tiny (pretrained) | 7,729 | 5,479 | 10,020 | 8,545 | 10,731 |
| Always long (control) | 6,771 | 6,771 | 12,713 | 8,186 | – |
| Tomorrow = today (control) | 8,876 | 7,046 | 10,356 | 9,407 | – |
| Random coin (control) | 9,156 | 7,614 | 11,222 | 9,375 | – |
| Ensemble (majority vote) | 9,549 | 9,551 | 9,955 | 9,795 | – |
| Kronos | 8,455 | 6,370 | 9,846 | 8,964 | 11,086 |
| LSTM on candle shape | 9,060 | 8,976 | 11,271 | 9,011 | – |
| AutoETS (statsforecast) | 9,953 | 9,686 | 11,551 | 10,119 | 10,961 |
| TimesFM | 9,188 | 7,475 | 11,233 | 9,208 | 10,782 |
| XGBoost on indicators | 8,399 | 7,547 | 11,168 | 8,306 | – |

Buy and hold with fees (the always-long control under the hold rule) ended at 12,713, and no model's hold account beat it. Under the one-day rules no model clearly beats the random control (9,156): two finished higher, the candlestick rules and AutoETS, but not by a margin that can be told apart from luck. These are backtest figures on one year of data. They say nothing certain about the future. Backtest figures are fixed between backfills, because the daily run scores only the live store. They change when a backfill is re-run or data is corrected; the dashboard is the current source of truth, and `data/` is the record.

These are simple estimators on one year of one market regime. The result says these particular tools, on these rules, showed no skill. It does not say prediction is impossible. The live record, which starts with the first scheduled run, is the real test.

## Adding an estimator

An estimator is a folder with a `predict.py`, plus one registry entry.

1. Create `estimators/<name>/__init__.py` and `estimators/<name>/predict.py` with a class that subclasses `estimators.base.Estimator` and implements:

   ```python
   def predict(self, history, assets):
       # history: {asset: candle DataFrame up to and including the prediction date}
       # assets:  the assets to predict
       # return {asset: Prediction(expected_return, confidence=None, path=None)}
   ```

   `expected_return` is the predicted close-to-close return of the next session. Rules (checked by the contract test): return only assets you were asked about, finite numbers only, omit an asset you have too little history for, be deterministic, do not modify the input, and do not touch the network (the harness supplies all data). The harness only ever shows you candles up to the prediction date.
2. Add an entry to `estimators/registry.py`: `target` (`module:Class`), `label`, `kind`, `source` (what it is and where the idea came from), `license`, `original_code` (true if it wraps the upstream code, false for a reimplementation), and `requirements` (path to a `requirements.txt`) if it needs packages beyond the shared ones. A heavy estimator can set `backfill_stride` in its registry entry so the backtest runs it every Nth day (the dashboard then marks its backtest balance as not comparable); the default is 1 and all current estimators use 1. Measure the runtime first (see `docs/runtime-notes.md`).
3. Run `python -m pytest tests/test_estimator_contract.py`. The contract test runs automatically for every registry entry. It must pass before the estimator joins.
4. Check the licence of anything you wrap or copy. This repo is public: third-party code is included only if its licence allows it, and the estimator's `license` field says which one. Record why an estimator was adopted, reimplemented or dropped in a short note under `docs/estimators/`.
5. Run `python -m bench.cli backfill --estimator <name>` locally, or trigger the `backfill` workflow, to give it a backtest record. Do not tune an estimator to improve its score: a bench that edits models until they win measures the editing.

## Running locally

Python 3.12 or newer, and a recent Node.js (only for the dashboard's own tests).

```sh
python -m venv .venv
. .venv/bin/activate    # on Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q
node --test site/lib.test.js
python scripts/verify_data.py data
```

To see the dashboard on your machine:

```sh
python -m bench.cli aggregate
python -m http.server -d site 8000
```

Then open http://localhost:8000. `aggregate` writes `site/data/`, which is not committed.

Other commands: `python -m bench.cli fetch` refreshes the price cache in `data/prices/`, `python -m bench.cli backfill --estimator <name> --days 365` replays the past, and `python -m bench.cli run --estimator <name> --run-date YYYY-MM-DD` does one live day (it only predicts within 11 hours after 00:00 UTC of that date, by design). `python -m bench.cli score --mode live|backtest|all` rescores every account from the stored predictions. Data layout (store schema 2): `data/live/` and `data/backtest/` each hold `estimators/<name>/` with `predictions/` and `runs.jsonl`, and `accounts/<model>/<strategy>/` with `ledger.csv`, `equity.csv` and `positions.json`.

To reset a backtest, delete `data/backtest/estimators/<name>` (or the whole `data/backtest/estimators` folder), commit, and run the `backfill` workflow from the Actions tab. Live data is never reset.

## Secrets

There is one secret: `NTFY_TOPIC`, the name of the ntfy topic that receives the daily message. Anyone who knows the topic name can read and post to it, so treat it like a password.

- The repository owner sets it with `gh secret set NTFY_TOPIC` (or in the repository's Settings, under Secrets and variables, Actions). Without it, the notify step skips quietly.
- It is read only from the secret, in the notify step of the workflow. Never commit it, paste it into an issue, or print it in a log. A test (`tests/test_capabilities.py`) fails if a topic-shaped URL appears in the code or workflows.
- **This repository is public, so nothing secret may ever be committed.** If a secret is ever committed, rotate it (a new topic name) rather than just deleting it.

## Roadmap (V2)

1. **Hold-while-bullish accounts** (built in part 1: the `hold` account; its dashboard view arrives in part 2).
2. **Per-estimator holdings view:** what each model's money is currently in: positions, size, entry, unrealised profit or loss.
3. **Shorting accounts** (built in part 1: the `one_day_short` account; its dashboard view arrives in part 2). Crypto shorts are a simplification, see Costs.
4. **Copy-trading estimators** from public disclosures: SEC Form 4 insider filings first, then Congress STOCK Act filings and 13F holdings. Keyed on the disclosure date, not the trade date, so the estimator only acts on what was public.
5. **Inverse-tipster estimator:** needs a named tipster with readable, timestamped posts.
6. **Dashboard navigation rework:** replace the scrolling tab bar with a side menu: Live and Backtest at the top, then a drop-down of all models sorted by wallet size, largest first, with each wallet amount shown in its box.

## Estimators

Eleven live accounts: three controls and eight estimators. Each has a short note under `docs/estimators/` where it needed one.

- **Controls:** always long (`control_always_long`), a random coin (`control_random`), and tomorrow equals today (`control_persistence`).
- **Estimators:** `analog` (candle matching), `xgb_indicators` (XGBoost on indicators), `candle_rules` (textbook candlestick patterns), `statsforecast_auto` (AutoETS), `kronos` (Kronos-small, pretrained), `timesfm` (TimesFM 2.5, pretrained), `chronos` (Chronos-Bolt Tiny, pretrained) and `lstm` (small LSTM on candle shape).

Candidates that were looked at and dropped:

- `Venon282/candlesticks_predictions` and `nsarang/big-data-stock-price-forecast`: no licence, so the code cannot be included in a public repository.
- neural-candlestick: a 2019 Flask and Theano stack, not an installable package.
- CandleEdge: a browser tool with no importable module and no next-day prediction.

## Operations

Two caveats for whoever runs the workflows by hand:

- **Use "Run workflow", not "Re-run failed jobs", for a daily run.** A new dispatch starts from the current commit inside the live window. A re-run reuses the original commit, so its data rebase can conflict with what has been committed since.
- **GitHub keeps at most one pending run per concurrency group.** The daily and backfill workflows share the `bench-data` group, so if a dispatch arrives while the 00:30 UTC daily is queued behind a running backfill, GitHub can cancel that queued daily without any notification. Do not start backfills near 00:30 UTC.

## Help and maintenance

This is a personal experiment, maintained by the repository owner. For a problem or a question, open an issue on this repository. There is no support commitment.

Other documents: `docs/superpowers/specs/` (design), `docs/superpowers/plans/` (build plan), `docs/data-sources.md` (the price source, its limits and fallback), `docs/runtime-notes.md` (measured run times), `docs/rulebook-checklist.md` (how the build measures up against its coding rulebook, including the open findings).
