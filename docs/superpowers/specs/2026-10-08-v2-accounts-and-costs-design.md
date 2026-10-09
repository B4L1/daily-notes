# V2 part 1: account types and realistic costs

Date: 2026-10-08. Status: draft for owner review.

This is part 1 of four V2 parts. Parts 2 to 4 (dashboard rebuild, more models, new data sources) get their own design documents.

## 1. Purpose

V1 gives each model one account under one rule: buy at the open, sell at the close, flat 0.1% cost. That answers one question. The owner wants to judge the same predictions in more ways, and under costs that match reality, so that:

- a model that is good at predicting falls gets credit for it,
- a model that is right but loses to fees can be told apart from a model that is wrong,
- a model that is poor at tomorrow but better at next week shows up,
- results can be read per asset category (stocks, ETFs, commodities, crypto).

Success means: every model has five comparable accounts scored from one set of stored predictions; every trading decision uses the real cost of the asset traded; the one-year backtest and the live record both use the same rules; nothing about prediction timing or the no-look-ahead guarantee changes.

## 2. What the owner decided

- Hold rule: buy when the expected gain beats the cost; sell at the next open once the model stops expecting a gain.
- Shorting: a second one-day account per model that also shorts. No shorting in hold accounts.
- Weekly: daily slices (one fifth of the account per day in 5-day positions), kept next to the one-day account for comparison.
- Top picks: the 3 strongest calls of the day.
- Ensemble: majority vote of the models; its own view on the dashboard.
- Buy-and-hold with fees as an honest baseline.
- Realistic per-asset costs for every account, including the original eleven. The flat 0.1% is retired. No live day has settled, so no history is broken.
- Pairs trading and arbitrage: left out.

## 3. Structure

An **account** is one model's predictions scored under one **strategy** (trading rule).

- Models run once a day, one job each, exactly as now. They only write predictions.
- A new scoring step runs once afterwards and settles every account under every strategy. It is pure arithmetic on stored predictions and prices.
- Because scoring is separate from predicting, the whole backtest can be rescored in seconds when a rule or cost changes, without re-running any model.

Storage, per mode (`data/live`, `data/backtest`):

```
estimators/<model>/predictions/<run_date>.json   unchanged
estimators/<model>/runs.jsonl                    unchanged
accounts/<model>/<strategy>/ledger.csv           one row per closed or open position event
accounts/<model>/<strategy>/equity.csv           one row per settled day
accounts/<model>/<strategy>/positions.json       open positions (hold, weekly), for the holdings view
```

The V1 files `estimators/<model>/ledger.csv` and `equity.csv` are removed; the `one_day` strategy replaces them. The store schema version goes from 1 to 2.

New code units, each with one job:

- `bench/costs.py`: cost of trading an asset (entry, exit, borrow per day). Reads `assets.yaml`.
- `bench/strategies/`: one module per rule, each a pure function from (predictions, prices, costs, previous state) to (ledger rows, equity rows, new state).
- `bench/scorer.py`: runs every strategy for every model; replaces the settle call inside the runner.
- `estimators/ensemble/`: a derived prediction set (see 4.6), not a model.

`bench/broker.py` becomes the `one_day` strategy. `bench/runner.py` keeps prediction, the live window and the stale-candle guard, and loses settlement.

## 4. Strategies

Shared definitions. A prediction with as-of date L targets the next candle after L (day T). `cost(asset)` is the round-trip cost of that asset (section 5). An account's day return is the sum of its position returns for the day divided by a universe count, so cash dilutes the result as in V1. For the one-day rules the count is the assets with a session that day. For `hold` and `weekly`, which keep positions over days when their asset has no session, the count is every asset listed by that date, so each asset has a fixed equal share and the account is never more than 100% invested (amended 2026-10-09 after the final review found weekend over-exposure). Equity compounds and never resets.

### 4.1 `one_day` (the V1 rule under new costs)

Trade when `expected_return > cost(asset)`. Enter at T's open, exit at T's close. Net return = close/open - 1 - cost(asset).

### 4.2 `one_day_short`

As 4.1, and also: when `expected_return < -cost(asset)`, short at T's open and buy back at T's close. Net return of a short = `-(close/open - 1) - cost(asset) - borrow_day(asset)`. Otherwise cash. The difference between this account and `one_day` is exactly what the model's down-calls are worth.

### 4.3 `hold`

- Not holding: buy at T's open when `expected_return > cost(asset)`. Pay the entry half of the cost.
- Holding: keep the position while the newest prediction has `expected_return > 0`. Holding costs nothing.
- Holding and the newest prediction has `expected_return <= 0`, or the model made no prediction for that asset that day: sell at T's open. Pay the exit half of the cost.
- Daily mark: an open position contributes close-to-close return on days it is held, open-to-close on its entry day, and previous-close-to-open on its exit day. Overnight moves are therefore earned, which V1 never did.
- The buy threshold is the full round trip so that the account never enters a trade it expects to lose on; the keep threshold is zero so that it does not sell and rebuy on small changes.

### 4.4 `top_picks`

Rank the day's predictions by `expected_return`, keep those above `cost(asset)`, take the top 3. Trade them as in 4.1. Fewer than 3 qualifying means fewer trades.

### 4.5 `weekly`

Only for models whose predictions carry a 5-day path (currently Kronos, TimesFM, Chronos, statsforecast, LSTM). The 5-day expected return is `path[4] / last_close - 1`.

- Each day, one fifth of the account is allocated to that day's batch. Within the batch, buy at T's open every asset whose 5-day expected return beats `cost(asset)`; the batch is split across the session's assets as in V1.
- A batch is sold at the close of its fifth session. One round-trip cost per position.
- Five batches overlap. The account's day return is the mean of the five batches' day returns.
- Reported next to the model's `one_day` account, with the difference in mean daily return over common dates, and a 5-day hit rate (was the close on day 5 above the entry-day previous close) next to the 1-day hit rate.

### 4.6 Ensemble

A derived prediction set, written to `estimators/ensemble/predictions/` by the scoring step before strategies run. For each asset: count voting models with `expected_return > cost(asset)`. If more than half of the models that predicted that asset vote up, the ensemble's prediction is +1; if more than half have `expected_return < -cost(asset)`, it is -1; otherwise 0. Ties are 0. The three controls do not vote. The ensemble then goes through `one_day`, `one_day_short`, `hold` and `top_picks` like any model. It has no path, so no `weekly`.

### 4.7 Buy-and-hold with fees

No new code: the always-long control under `hold`. It buys every asset once, pays the entry cost once and holds. This replaces the cost-free hold line as the honest baseline; the cost-free line is dropped.

## 5. Costs

Costs live per asset in `assets.yaml` as `cost_round_trip` and `borrow_annual`. `settings.cost_round_trip` and `settings.trade_threshold` are removed; the threshold is always the asset's own cost.

Assets are regrouped so the category split is clean: SPY and QQQ move from `stock` to `etf`.

Proposed figures (round trip = buy and sell, as a fraction of the position):

| Group | Assets | Round trip | Short borrow, per year | Basis |
|---|---|---|---|---|
| ETF | SPY, QQQ | 0.01% | 0.5% | Quoted spreads of 0.0032% (SPY) and 0.0041% (QQQ); rounded up; zero commission |
| Stock | 13 large US stocks | 0.05% | 0.5% | US equity spreads range 2 to 20 basis points with a median of 9; large caps sit at the low end; zero commission |
| Commodity | GLD, SLV, USO | 0.03% | 0.5% | GLD quoted spread 0.0065%; SLV and USO not found, assumed wider |
| Crypto | BTC, ETH, SOL | 0.25% | 10% | 0.1% taker fee per side at the cheapest major exchange, plus spread |

Borrow is charged per calendar day held: `borrow_annual / 360`.

**Unverified, and for the owner to check:**
- SLV and USO spreads were not found; 0.03% is an assumption.
- The stock figure is a judgement inside a published range, not a per-stock measurement.
- The crypto short cost (10% a year) is an assumption. Real crypto shorting uses derivatives with a funding rate that changes daily and can be negative. The README will say crypto shorts are a simplification.
- Crypto fees depend heavily on the exchange: 0.1% per side at Binance, 0.26% at Kraken's base tier, 0.40% to 1.20% at Coinbase Advanced for small accounts. 0.25% round trip is the cheap end.

**Not modelled, stated in the README:** broker-specific charges. At XTB, real stocks and ETFs are commission-free up to 100,000 EUR of monthly turnover, then 0.2%; a $10,000 account trading every day passes that limit. XTB also charges 0.5% for currency conversion when the account currency differs from the asset's, which is 1% per round trip and would outweigh every other cost here. The bench assumes a USD account at a low-cost broker. Slippage beyond the spread and market impact are also not modelled; at $10,000 they are negligible for these assets.

Sources: [ETF spreads, etf.com](https://www.etf.com/sections/news/why-trading-spreads-matter-etfs); [XTB fees](https://www.xtb.com/en/help-center/instruments/do-you-charge-commissions); [crypto fee comparison](https://www.spark.money/tools/crypto-exchange-fee-comparison); [borrow fees, Interactive Brokers](https://www.interactivebrokers.com/campus/traders-insight/securities/short-selling/the-risks-of-shorting-series-part-ii-borrow-fees/).

## 6. Scoring

- **Baseline per strategy.** Every strategy is also run for the random control. A model's account is compared with the random control's account under the same strategy. Edge and the luck test use that pairing.
- **Luck test.** Bonferroni within each strategy: 0.05 divided by the number of non-control accounts in that strategy. The dashboard states the threshold, as now.
- **Category split.** For every account: return contribution, number of trades and hit rate per group (stock, ETF, commodity, crypto), written into the summary and the per-account detail.
- **Hit rates.** 1-day direction hit rate as in V1. For `weekly`, the 5-day hit rate as well. For shorts, a hit is a fall.
- **Too early to tell** stays at 60 live days.
- Sanity flag, maximum drawdown and worst day are computed per account.

## 7. How it runs

Daily workflow: `fetch` -> `predict` (one job per model, predictions only) -> `score` (new; ensemble, then every strategy for every model, then verify) -> `aggregate` -> `deploy` -> `notify`. The `score` and `aggregate` steps run in one job, since both need all the predictions.

Backfill: the existing backfill produces predictions. Scoring the backtest is a separate, fast command (`bench.cli score --mode backtest`) that can be re-run at will. After this part ships, the stored backtest predictions are rescored once; no model is re-run.

Migration, in one commit: schema version 2; V1 ledgers and equity files deleted; backtest rescored; live accounts start empty (they are empty today).

Idempotency: scoring a day twice gives identical files. Hold and weekly state is rebuilt from the ledger, so a deleted `positions.json` is recoverable.

## 8. Errors and edge cases

- A model with no prediction file for a day: its accounts stay in cash that day; under `hold`, open positions are sold at the next open (4.3), so a broken model cannot sit in stale positions.
- A stale asset (skipped by the guard): no new trade; a held position in it is kept and marked at its last close until a candle arrives, and is listed on the dashboard as stale.
- An asset with no session (weekend stocks): held positions are carried unchanged; weekly batches count sessions, not calendar days.
- A late candle for one asset: settlement is tracked per (asset, date), not by one shared date, so the trade is settled when the candle arrives. This fixes a V1 minor.
- Non-finite numbers anywhere in scoring fail the scoring step loudly; nothing is written.
- Short loss on a one-day short is bounded by the day's move; equity cannot go below zero (floored, and flagged).

## 9. Testing

- Each strategy against hand-worked examples: a 3-day hold with entry and exit costs computed by hand; a short on a falling and on a rising day; five overlapping weekly batches; top picks with fewer than 3 qualifying; ensemble ties.
- No look-ahead: changing any candle after day T never changes a decision made for T, for every strategy.
- Rescoring twice is byte-identical. Rescoring after deleting `positions.json` is identical.
- Cost threshold: a prediction just below an asset's cost never trades; the same prediction trades on a cheaper asset.
- `one_day` under a flat 0.1% cost reproduces the V1 ledger for one stored backtest model, proving the refactor changed nothing but the costs.
- `scripts/verify_data.py` extended: every account's equity compounds from its ledger; open positions match the ledger; crypto predictions have as-of equal to run date minus 1.
- Workflow tests updated for the new job order.

## 10. Out of scope

The dashboard views for all of this (part 2: side menu, holdings view, category split, predicted-versus-actual, ticker redesign, React and Bklit rebuild, deploy on code push). New models (part 3). Copy-trading and the inverse tipster (part 4). The summary JSON will carry the new data from this part, and the current dashboard will show only the `one_day` accounts until part 2 lands.
