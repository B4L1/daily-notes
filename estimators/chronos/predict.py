import os

import numpy as np

from estimators.adapter import ClosesForecaster
from estimators.chronos.fetch_assets import weights_dir, weights_ok


class Chronos(ClosesForecaster):
    """Chronos-Bolt (Tiny, 9M, pretrained time-series foundation model), median forecast, 5-day close path.

    Needs `python -m bench.cli setup --estimator chronos` to have run once (pinned, sha256-verified
    weights in data/cache); predict itself never touches the network. Chronos-Bolt decodes quantiles
    directly (no sampling); we use the 0.5 quantile, so the output is deterministic.
    """

    name = "chronos"
    window = 512
    horizon = 5

    def __init__(self):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # the weights come from the local directory only
        import torch  # imported here so the registry lists this estimator without the dependency

        if not weights_ok():
            raise ImportError("chronos weights missing or altered; run `python -m bench.cli setup --estimator chronos`")
        from chronos import ChronosBoltPipeline

        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        self._torch = torch
        self._pipe = ChronosBoltPipeline.from_pretrained(
            str(weights_dir()), device_map="cpu", torch_dtype=torch.float32, local_files_only=True)

    def _forecast(self, df, horizon):
        x = self._torch.tensor(df["close"].to_numpy(float), dtype=self._torch.float32)
        with self._torch.no_grad():
            quantiles, _ = self._pipe.predict_quantiles(
                [x], prediction_length=horizon, quantile_levels=[0.5])
        return np.asarray(quantiles[0, :, 0].numpy(), dtype=float)
