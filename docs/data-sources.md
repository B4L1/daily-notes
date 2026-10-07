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

**Fallback plan:** If yfinance breaks:
- Stocks and ETFs: Stooq CSV export (https://stooq.com/) - unconfirmed auth, rate limit, licence
- Crypto: Public exchange API (e.g., CoinGecko, Kraken) - unconfirmed auth, rate limit, licence for both
- Design note: `fetch_asset()` is the single network seam by design; switching data sources requires only replacing this function in `bench/data.py`

**Observed (2026-10-06):** Smoke test fetched 25 days of SPY data (9/1–10/6) and 36 days of BTC-USD data (9/1–10/6). Both datasets are daily candles. yfinance is operational. Note: Newest row on 2026-10-06 appeared to be a partial intraday candle (SPY volume ~half typical), but this behavior is unverified and may vary by trading session.
