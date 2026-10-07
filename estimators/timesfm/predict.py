import os

import numpy as np

from estimators.adapter import ClosesForecaster
from estimators.timesfm.fetch_assets import weights_dir, weights_ok


class TimesFM(ClosesForecaster):
    """TimesFM 2.5 (200M, pretrained time-series foundation model), point forecast, 5-day close path.

    Needs `python -m bench.cli setup --estimator timesfm` to have run once (pinned, sha256-verified
    weights in data/cache); predict itself never touches the network.
    """

    name = "timesfm"
    window = 512
    horizon = 5
    backfill_stride = 2  # about 0.9 s per asset-day on 16 CPUs; see docs/estimators/timesfm.md

    def __init__(self):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # the weights come from the local directory only
        import torch  # imported here so the registry lists this estimator without the dependency

        if not weights_ok():
            raise ImportError("timesfm weights missing or altered; run `python -m bench.cli setup --estimator timesfm`")
        import timesfm

        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(str(weights_dir()), local_files_only=True)
        self._model.compile(timesfm.ForecastConfig(
            max_context=512, max_horizon=8, normalize_inputs=True,
            use_continuous_quantile_head=True, force_flip_invariance=True,
            infer_is_positive=True, fix_quantile_crossing=True,
        ))

    def _forecast(self, df, horizon):
        point, _ = self._model.forecast(horizon=horizon, inputs=[df["close"].to_numpy(float)])
        return np.asarray(point[0], dtype=float)
