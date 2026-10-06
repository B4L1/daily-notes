from datetime import date, timedelta

import numpy as np
import pandas as pd


def candles(rows):
    """rows: (date, open, high, low, close) tuples -> candle DataFrame."""
    return pd.DataFrame(
        [
            {"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1}
            for d, o, h, l, c in rows
        ]
    )


def random_walk(n, start="2024-01-01", seed=0, daily_vol=0.01):
    """n consecutive calendar days of synthetic candles, deterministic per seed."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, daily_vol, n)
    close = 100 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    d0 = date.fromisoformat(start)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(n)]
    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": 1000}
    )
