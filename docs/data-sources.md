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

**Important implementation caveat:** yfinance's `auto_adjust=True` parameter (used in `fetch_asset()`) rewrites historical prices after dividends and splits. The cache refreshes only the last 10 days, so older cached rows retain their earlier adjustment base; this mix is NOT verified. Open-to-close returns within a single day are unaffected by the adjustment base (acceptable for this project's daily open-to-close trading), but close-to-close returns spanning the merge boundary could be distorted for the first days after a corporate action (unverified). (Source: yfinance auto_adjust behavior; caveat inferred, not smoke-tested)

**Fallback plan:** If yfinance breaks:
- Stocks and ETFs: Stooq CSV export (https://stooq.com/) - unconfirmed auth, rate limit, licence
- Crypto: Public exchange API (e.g., CoinGecko, Kraken) - unconfirmed auth, rate limit, licence for both
- Design note: `fetch_asset()` is the single network seam by design; switching data sources requires only replacing this function in `bench/data.py`

**Observed (2026-10-06):** Smoke test fetched 25 days of SPY data (9/1–10/6) and 36 days of BTC-USD data (9/1–10/6). Both datasets are daily candles. yfinance is operational. Note: Newest row on 2026-10-06 appeared to be a partial intraday candle (SPY volume ~half typical), but this behavior is unverified and may vary by trading session.
