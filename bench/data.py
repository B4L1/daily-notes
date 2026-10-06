from datetime import date, timedelta
from pathlib import Path

import pandas as pd

COLUMNS = ["date", "open", "high", "low", "close", "volume"]
PRICE_COLS = ["open", "high", "low", "close"]


def normalize(raw):
    """yfinance history frame -> candle frame with ISO session dates."""
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=COLUMNS)
    df = raw.rename(columns=str.lower)[PRICE_COLS + ["volume"]].copy()
    df.insert(0, "date", [ts.date().isoformat() for ts in df.index])
    df = df.dropna(subset=PRICE_COLS)
    df = df[(df[PRICE_COLS] > 0).all(axis=1)]
    return df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)


def fetch_asset(symbol, start):
    """The only function that touches the network. Replace this to change data source."""
    import yfinance as yf

    raw = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=True)
    return normalize(raw)


def merge_candles(old, new):
    both = new.copy() if len(old) == 0 else pd.concat([old, new], ignore_index=True)
    return both.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)


def _path(prices_dir, symbol):
    return Path(prices_dir) / f"{symbol}.csv"


def _read(path):
    if path.exists():
        return pd.read_csv(path, dtype={"date": str})
    return pd.DataFrame(columns=COLUMNS)


def load_prices(prices_dir, assets):
    return {a.symbol: _read(_path(prices_dir, a.symbol)) for a in assets}


def update_prices(prices_dir, assets, start, fetch=fetch_asset):
    """Refresh every asset's cache. A failure or an empty result never touches the cache."""
    Path(prices_dir).mkdir(parents=True, exist_ok=True)
    status = {}
    for a in assets:
        path = _path(prices_dir, a.symbol)
        old = _read(path)
        since = start
        if not old.empty:
            since = (date.fromisoformat(old["date"].iloc[-1]) - timedelta(days=10)).isoformat()
        try:
            new = fetch(a.symbol, since)
            if new is None or len(new) == 0:
                raise ValueError("no rows returned")
            merge_candles(old, new).to_csv(path, index=False, lineterminator="\n")
            status[a.symbol] = "ok"
        except Exception as e:  # recorded, never raised: one bad asset must not stop the run
            status[a.symbol] = f"error: {type(e).__name__}: {e}"
    return status


def stale_assets(prices, assets, run_date):
    """Assets whose newest completed candle is too old. None means no data at all."""
    cutoff = date.fromisoformat(run_date) - timedelta(days=1)
    out = {}
    for a in assets:
        df = prices.get(a.symbol)
        seen = df[df["date"] <= cutoff.isoformat()] if df is not None and len(df) else None
        if seen is None or len(seen) == 0:
            out[a.symbol] = None
            continue
        gap = (cutoff - date.fromisoformat(seen["date"].iloc[-1])).days
        if gap > a.max_gap_days:
            out[a.symbol] = gap
    return out
