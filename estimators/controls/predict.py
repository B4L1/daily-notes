import hashlib

from estimators.base import Estimator, Prediction


class AlwaysLong(Estimator):
    name = "control_always_long"

    def predict(self, history, assets):
        return {a: Prediction(1.0) for a in assets if len(history[a])}


class RandomCoin(Estimator):
    name = "control_random"

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if not len(df):
                continue
            digest = hashlib.sha256(f"{a}:{df['date'].iloc[-1]}".encode()).digest()
            out[a] = Prediction(1.0 if digest[0] % 2 == 0 else -1.0)
        return out


class Persistence(Estimator):
    name = "control_persistence"

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if len(df) < 2:
                continue
            out[a] = Prediction(float(df["close"].iloc[-1] / df["close"].iloc[-2] - 1.0))
        return out
