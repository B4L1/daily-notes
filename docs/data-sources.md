# Data Sources

## yfinance

**Verified:** 2026-10-06

**URL:** https://github.com/ranaroussi/yfinance

**Description:** Unofficial Python wrapper around Yahoo Finance's public endpoints for downloading market data. (Source: context7 yfinance docs)

**Auth:** None; no API key required. (Source: context7 yfinance docs)

**Free tier:** Yes, public data at no cost. (Source: smoke test, 2026-10-06)

**Rate limit:** No published limit stated. Yahoo Finance may throttle or block the client without notice. (Source: context7 yfinance docs; `YFRateLimitError` exception; README states "Try after a while")

**Licence / ToS constraints:** 
- Software licence: Apache-2.0 (Source: context7 yfinance docs, LICENSE.txt file)
- Data usage: Yahoo's terms restrict use to personal use only. yfinance is not affiliated with Yahoo, Inc. (Source: context7 yfinance docs README)

**Price basis (decided 2026-10-07):** `fetch_asset()` uses `auto_adjust=False` and `normalize()` takes the `Open`/`High`/`Low`/`Close` columns (never `Adj Close`). These are raw prices: adjusted for splits but NOT for dividends, so settled history is not rewritten by later dividends. Reason: with `auto_adjust=True` a refresh of the last ~10 days carried a new adjustment base while settled ledger entry/exit prices and older cached rows kept the old one, and `scripts/verify_data.py` failed in CI with "ledger row ... does not match the candle" (observed in the first cloud run; the adjustment mechanism is the diagnosed cause, not re-proven against Yahoo). A split could still retroactively re-base history (unverified how yfinance handles it for already-cached rows).

**Incomplete candles:** `update_prices` never stores a candle dated after the last completed session day (run date minus 1, or yesterday UTC by default), so an intraday partial candle is never cached.

**Corrections and splits:** the price cache is append-only. `update_prices` re-fetches the last 10 days but never overwrites a stored date; it only adds dates it has not seen. If the source reports different OHLC for a stored date (more than 1e-6 relative), the old value is kept and `python -m bench.cli fetch` prints a `WARNING` line naming the asset, date and old/new values. Ledger consistency wins: settled trades keep the prices they were settled with, so a small correction at the source is warned about and otherwise ignored. If the revision is one constant ratio more than 2% from 1 across all overlapping days, the line also says "possible split: manual re-base needed" and `fetch` exits non-zero (the workflow stops before committing). Manual re-base for an asset: delete `data/prices/<SYMBOL>.csv`, delete the backtest and live ledger rows that depend on it (or, more simply, delete `data/backtest/estimators` and re-run the backfills; live rows after the split date cannot be recomputed and should be annotated or dropped by hand), then run `fetch` so the file is rebuilt from the source's current, re-based history, and run `scripts/verify_data.py data`. This procedure has not been rehearsed against a real split.

**Fallback plan:** If yfinance breaks:
- Stocks and ETFs: Stooq CSV export (https://stooq.com/) - unconfirmed auth, rate limit, licence
- Crypto: Public exchange API (e.g., CoinGecko, Kraken) - unconfirmed auth, rate limit, licence for both
- Design note: `fetch_asset()` is the single network seam by design; switching data sources requires only replacing this function in `bench/data.py`

**Observed (2026-10-06):** Smoke test fetched 25 days of SPY data (9/1–10/6) and 36 days of BTC-USD data (9/1–10/6). Both datasets are daily candles. yfinance is operational. Note: Newest row on 2026-10-06 appeared to be a partial intraday candle (SPY volume ~half typical), but this behavior is unverified and may vary by trading session.
