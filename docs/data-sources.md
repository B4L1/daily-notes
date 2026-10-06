# Data Sources

## yfinance

**Verified:** 2026-10-06

**URL:** https://github.com/ranaroussi/yfinance

**Description:** Unofficial Python wrapper around Yahoo Finance's public endpoints for downloading market data.

**Auth:** None (no API key required)

**Free tier:** Yes, unlimited public data

**Rate limit:** No published limit. Yahoo Finance may throttle or block the client without notice. Implement exponential backoff with jitter for retries.

**Licence / ToS constraints:** 
- Software licence: Apache-2.0
- Data usage: Yahoo's terms restrict use to personal use only. yfinance is not affiliated with Yahoo, Inc.

**Fallback plan:** If yfinance breaks:
- Stocks and ETFs: Stooq CSV export (https://stooq.com/)
- Crypto: Use a public exchange API (e.g., CoinGecko, Kraken)
- Migration: Switching data sources requires only replacing the `fetch_asset()` function in `bench/data.py`

**Observed (2026-10-06):** Smoke test fetched 25 days of SPY data and 36 days of BTC-USD data, both current to 2026-10-06. yfinance is operational and returning real-time market data.
