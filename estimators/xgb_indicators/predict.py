import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from estimators.base import Estimator, Prediction

FEATURES = [
    "ret1", "ret2", "ret3", "ret4", "ret5", "rsi14", "sma20", "sma50", "vol20", "range", "body",
]


def _features(df):
    c, o = df["close"].astype(float), df["open"].astype(float)
    h, l = df["high"].astype(float), df["low"].astype(float)
    r = c.pct_change()
    f = pd.DataFrame({f"ret{k}": r.shift(k - 1) for k in range(1, 6)})
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = 100 - 100 / (1 + gain / (loss + 1e-12))
    f["sma20"] = c / c.rolling(20).mean() - 1
    f["sma50"] = c / c.rolling(50).mean() - 1
    f["vol20"] = r.rolling(20).std()
    f["range"] = (h - l) / c
    f["body"] = (c - o) / o
    f["target"] = r.shift(-1)  # the next session's close-to-close return
    return f


class XgbIndicators(Estimator):
    """Gradient-boosted trees on common technical indicators, pooled across assets.

    Retrained from the truncated history on every run (walk-forward by construction).
    """

    name = "xgb_indicators"

    def __init__(self, min_rows=120, min_train=500):
        self.min_rows, self.min_train = min_rows, min_train

    def predict(self, history, assets):
        frames = {a: _features(df) for a, df in history.items() if len(df) >= self.min_rows}
        train = pd.concat(
            [f.dropna(subset=FEATURES + ["target"]) for f in frames.values()], ignore_index=True
        ) if frames else pd.DataFrame()
        if len(train) < self.min_train:
            return {}
        model = XGBRegressor(
            n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8,
            tree_method="hist", random_state=0, n_jobs=1,
        )
        model.fit(train[FEATURES].to_numpy(float), train["target"].to_numpy(float))
        out = {}
        for a in assets:
            if a not in frames:
                continue
            last = frames[a].iloc[-1][FEATURES]
            if last.isna().any():
                continue
            out[a] = Prediction(float(model.predict(np.array([last.to_numpy(float)]))[0]))
        return out
