import numpy as np

from estimators.adapter import ClosesForecaster


class StatsforecastAuto(ClosesForecaster):
    """AutoETS (Nixtla statsforecast) fitted on the last 256 closes, forecasting 5 closes.

    The model is fitted from scratch per asset per call; no pretrained weights, no network.
    """

    name = "statsforecast_auto"
    window = 256
    horizon = 5

    def _forecast(self, df, horizon):
        from statsforecast.models import AutoETS  # imported here so the registry lists it without the dependency

        model = AutoETS(season_length=1)
        model.fit(df["close"].to_numpy(float))
        return np.asarray(model.predict(h=horizon)["mean"], dtype=float)
