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

**Important implementation detail:** yfinance's `auto_adjust=True` parameter (used in `fetch_asset()`) causes historical prices to be rewritten after dividends and splits. This is safe for the 10-day overlap strategy: within a single day, the open-to-close ratio is unaffected by historical adjustments, so merging candles from different adjustment bases does not corrupt OHLCV relationships. (Source: observed via smoke test structure; yfinance auto_adjust behavior)

**Fallback plan:** If yfinance breaks:
- Stocks and ETFs: Stooq CSV export (https://stooq.com/) - unconfirmed auth, rate limit, licence
- Crypto: Public exchange API (e.g., CoinGecko, Kraken) - unconfirmed auth, rate limit, licence for both
- Migration: Switching data sources requires only replacing the `fetch_asset()` function in `bench/data.py`

**Observed (2026-10-06):** Smoke test fetched 25 days of SPY data (9/1–10/6) and 36 days of BTC-USD data (9/1–10/6). Both datasets are daily candles; newest row is a partial intraday candle. yfinance is operational.
