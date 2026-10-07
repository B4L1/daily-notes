import numpy as np

from estimators.base import Estimator, Prediction


class ClosesForecaster(Estimator):
    """Adapter for models that forecast future closes from a window of past candles.

    A subclass implements only `_forecast`. Everything else (windowing, minimum history,
    turning predicted closes into a Prediction with a path) is shared, so every such model
    is judged on the same footing.
    """

    window = 256
    horizon = 5
    min_rows = 300

    def _forecast(self, df, horizon):
        """df: the last `window` candles. Return `horizon` predicted future closes."""
        raise NotImplementedError

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if len(df) < self.min_rows:
                continue
            win = df.tail(self.window).reset_index(drop=True)
            closes = np.asarray(self._forecast(win, self.horizon), dtype=float)
            if closes.shape != (self.horizon,):
                raise ValueError(f"{self.name}: expected {self.horizon} closes, got shape {closes.shape}")
            last = float(win["close"].iloc[-1])
            out[a] = Prediction(float(closes[0] / last - 1.0), None, [float(x) for x in closes])
        return out
