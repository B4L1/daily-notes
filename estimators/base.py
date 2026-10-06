from dataclasses import dataclass


@dataclass(frozen=True)
class Prediction:
    expected_return: float  # expected close-to-close return of the asset's next session
    confidence: float | None = None
    path: list[float] | None = None  # predicted closes for the next sessions, if the model forecasts further


class Estimator:
    name = ""
    backfill_stride = 1  # backfill runs the estimator on every Nth day; the rest stay in cash

    def predict(self, history, assets):
        """history: {asset: candle DataFrame up to the cutoff}; return {asset: Prediction}."""
        raise NotImplementedError
