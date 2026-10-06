import numpy as np

from estimators.base import Estimator, Prediction


def _windows(df, k):
    """Row j describes candles j..j+k-1 as (body, upper wick, lower wick) relative to the open."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    base = np.column_stack([
        (c - o) / o,
        (h - np.maximum(o, c)) / o,
        (np.minimum(o, c) - l) / o,
    ])
    n = len(df)
    return np.hstack([base[i:n - k + 1 + i] for i in range(k)])


class Analog(Estimator):
    """Find the past stretches whose last few candles looked most like today's, average what came next.

    The idea comes from historical pattern-matching tools such as CandleEdge. This is our own
    small implementation of it, so it is a reimplementation, not the original code.
    """

    name = "analog"

    def __init__(self, window=3, neighbours=30, min_rows=250):
        self.window, self.neighbours, self.min_rows = window, neighbours, min_rows

    def predict(self, history, assets):
        k, out = self.window, {}
        for a in assets:
            df = history[a]
            if len(df) < self.min_rows:
                continue
            rows = _windows(df, k)
            past, query = rows[:-1], rows[-1]
            close = df["close"].to_numpy(float)
            nxt = close[k:] / close[k - 1:-1] - 1.0  # what followed each past window
            sd = past.std(axis=0) + 1e-12
            dist = np.linalg.norm((past - query) / sd, axis=1)
            idx = np.argsort(dist, kind="stable")[: self.neighbours]
            mean = float(nxt[idx].mean())
            agree = float((np.sign(nxt[idx]) == np.sign(mean)).mean())
            out[a] = Prediction(mean, agree)
        return out
