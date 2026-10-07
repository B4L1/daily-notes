# Prediction bench

A paper-trading bench that asks one question: does any price-prediction tool have real skill, or does it only look that way? Each tool (an "estimator") gets a simulated $10,000 account and trades on its own predictions every day, under the same rules as every other estimator, next to three controls (always long, a random coin flip, "tomorrow equals today"). A page shows every day of every account.

**This is an experiment, not investment advice.** No real money is involved, there is no broker connection, and nothing here recommends buying or selling anything. The data is public daily prices.

An inconclusive result ("nothing beats the random control") is a legitimate and likely outcome, and the dashboard reports it as one.

## How a day works

A scheduled GitHub Actions workflow (`.github/workflows/daily.yml`) runs at 00:30 UTC every day. That time is chosen so a prediction is always committed before the session it trades.

1. **Fetch** the latest completed daily candles for about 21 assets (`assets.yaml`: 15 US stocks and ETFs, 3 crypto, 3 commodity ETFs). Source: `yfinance` (unofficial, see `docs/data-sources.md`).
2. **Settle** the previous predictions against what actually happened and update each account.
3. **Predict** the next session. One job per estimator runs in parallel; a failing estimator is recorded as failed and the others carry on.
4. **Aggregate** the results into static JSON, verify the data, commit it, and deploy the dashboard to GitHub Pages.
5. **Notify** through [ntfy](https://ntfy.sh): one low-priority message per day with the best and worst return, how many estimators beat the random control, and a link.

The trading rules are the same for every account: the full balance carries over from day to day (no reset), the balance is split equally across assets that have a session, a trade enters at the next session's open and exits at its close, trading is long-only, and each trade costs 0.1% (fee plus slippage). An estimator trades an asset only when its predicted return is above that cost.

Two stated approximations:

- A crypto trade enters at the 00:00 UTC open, and its prediction is committed up to 12 hours later (the cron fires at 00:30 UTC but GitHub can start it late), using only data from before that day.
- Trading is open to close, so overnight gaps are ignored. That is why buy-and-hold is drawn as a reference line, not as an account.

## Reading the dashboard

The dashboard is a static page (no login, no input). The ntfy message links to it; its address is `https://<owner>.github.io/<repo>/`.

- **Live / Backtest switch.** Live is the real record: each prediction was committed before its session. Backtest replays the past year day by day, with each day seeing only earlier data. The two are separate accounts with separate charts, and are never combined. Pretrained models may have seen the backtest period in training, so their backtest numbers may be optimistic; live is the real verdict.
- **Wallet strip.** One tile per account: balance, today's change, a small sparkline. Sorted by balance. A "check this" badge appears on a gain of more than 10% in a day or 50% in a week, because returns that large are more likely a bug or a data leak than skill.
- **Hold line.** The dashed grey line on the charts is an equal-weight buy-and-hold of the same assets, close to close, with no costs. It is a reference, not an account.
- **Heatmaps.** One row per estimator, one column per day: (1) daily account return, (2) direction hit rate. Brighter means a bigger magnitude; green and red (or blue and orange, with the colour-blind palette button). Each cell also carries a sign marker in its tooltip.
- **Luck check.** For each estimator, a one-sided sign-flip permutation test on its daily return minus the random control's. "Unlikely luck" means p below 0.05; "consistent with luck" means it cannot be told apart from guessing.
- **"Too early to tell".** Shown in place of the luck check until an estimator has 60 live trading days (`min_live_days` in `assets.yaml`).
- **Estimator tabs.** Each estimator has its own tab: where it came from, its licence, its stats, calendar heatmaps, a per-asset breakdown, and a day-by-day table with predicted vs actual for every asset.

## What the backtest says so far

Backtest of 364 days (2025-10-07 to 2026-10-05) with six accounts (three controls and three estimators), computed from the committed data on 2026-10-06:

| Account | Final value of $10,000 | Luck check (p) |
|---|---|---|
| Buy and hold (reference, no costs) | about $12,760 | n/a |
| Candlestick pattern rules | about $10,030 | 0.44 |
| Random coin (control) | about $9,680 | n/a |
| Tomorrow = today (control) | about $9,460 | n/a |
| Analog candle matching | about $8,870 | 0.82 |
| XGBoost on indicators | about $8,020 | 0.93 |
| Always long (control) | about $7,440 | n/a |

The honest reading:

- **No estimator beats the random control.** Every estimator's luck-check p-value is far above 0.05, and edge over the random control is about zero. The candlestick rules finish near flat only because they trade rarely (under one trade a day, so they sit in cash most days).
- **Always-long loses to buy-and-hold** by a wide margin. The 0.1% cost is charged on every trade every day, which on its own is roughly a 22% drag over a year of trading days, and open-to-close trading skips the overnight gains that buy-and-hold keeps. This is the cost model working as designed, and it is why "just be long" is not a free baseline here.
- These are simple estimators on one year of one market regime. The result says these particular tools, on these rules, showed no skill. It does not say prediction is impossible. The live record, which starts with the first scheduled run, is the real test.

Numbers change as data arrives. The source of truth is `data/`.

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

Python 3.11 or newer, and a recent Node.js (only for the dashboard's own tests).

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

Other commands: `python -m bench.cli fetch` refreshes the price cache in `data/prices/`, `python -m bench.cli backfill --estimator <name> --days 365` replays the past, and `python -m bench.cli run --estimator <name> --run-date YYYY-MM-DD` does one live day (it only predicts within 12 hours after 00:00 UTC of that date, by design). Data layout: `data/live/` and `data/backtest/` each hold `estimators/<name>/` with `predictions/`, `ledger.csv`, `equity.csv` and `runs.jsonl`.

To reset a backtest, delete `data/backtest/estimators/<name>` (or the whole `data/backtest/estimators` folder), commit, and run the `backfill` workflow from the Actions tab. Live data is never reset.

## Secrets

There is one secret: `NTFY_TOPIC`, the name of the ntfy topic that receives the daily message. Anyone who knows the topic name can read and post to it, so treat it like a password.

- The repository owner sets it with `gh secret set NTFY_TOPIC` (or in the repository's Settings, under Secrets and variables, Actions). Without it, the notify step skips quietly.
- It is read only from the secret, in the notify step of the workflow. Never commit it, paste it into an issue, or print it in a log. A test (`tests/test_capabilities.py`) fails if a topic-shaped URL appears in the code or workflows.
- **This repository is public, so nothing secret may ever be committed.** If a secret is ever committed, rotate it (a new topic name) rather than just deleting it.

## Roadmap (V2)

1. **Hold-while-bullish accounts** as a separate account set with its own backfill: positions carried overnight, fees only when the position changes.
2. **Per-estimator holdings view:** what each model's money is currently in: positions, size, entry, unrealised profit or loss.
3. **Shorting accounts:** sell at the open and buy back at the close on predicted drops, with borrow fees. Crypto shorts need derivatives.
4. **Copy-trading estimators** from public disclosures: SEC Form 4 insider filings first, then Congress STOCK Act filings and 13F holdings. Keyed on the disclosure date, not the trade date, so the estimator only acts on what was public.
5. **Inverse-tipster estimator:** needs a named tipster with readable, timestamped posts.
6. **Heavier estimators still to come:** LSTM, Kronos, TimesFM, and the owner's four repositories (pending decisions on which repositories and their licences).

## Help and maintenance

This is a personal experiment, maintained by the repository owner. For a problem or a question, open an issue on this repository. There is no support commitment.

Other documents: `docs/superpowers/specs/` (design), `docs/superpowers/plans/` (build plan), `docs/data-sources.md` (the price source, its limits and fallback), `docs/runtime-notes.md` (measured run times), `docs/rulebook-checklist.md` (how the build measures up against its coding rulebook, including the open findings).
