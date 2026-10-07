import sys

import numpy as np
import pandas as pd

from estimators.adapter import ClosesForecaster
from estimators.kronos.fetch_assets import source_dir, weights_dir


class Kronos(ClosesForecaster):
    """Kronos-small (pretrained candlestick foundation model), greedy decoding, 5-day close path.

    Needs `python -m bench.cli setup --estimator kronos` to have run once (pinned source and
    weights in data/cache); predict itself never touches the network.
    """

    name = "kronos"
    window = 400
    horizon = 5
    backfill_stride = 3  # about 2 s per asset-day steady state on 16 CPUs; see docs/estimators/kronos.md

    def __init__(self):
        import torch  # imported here so the registry lists this estimator without the dependency

        src = source_dir().resolve()
        if not (src / "model" / "kronos.py").exists():
            raise ImportError("kronos source not prepared; run `python -m bench.cli setup --estimator kronos`")
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from model import Kronos as KronosModel, KronosPredictor, KronosTokenizer

        tok = weights_dir("NeoQuasar/Kronos-Tokenizer-base")
        mdl = weights_dir("NeoQuasar/Kronos-small")
        for d in (tok, mdl):
            if not (d / "model.safetensors").exists():
                raise ImportError("kronos weights not prepared; run `python -m bench.cli setup --estimator kronos`")
        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        self._torch = torch
        self._predictor = KronosPredictor(
            KronosModel.from_pretrained(str(mdl)).eval(), KronosTokenizer.from_pretrained(str(tok)).eval(),
            device="cpu", max_context=512,
        )

    def _forecast(self, df, horizon):
        self._torch.manual_seed(0)
        x = df[["open", "high", "low", "close", "volume"]].astype(float)
        x_ts = pd.Series(pd.to_datetime(df["date"]))
        y_ts = pd.Series(pd.bdate_range(x_ts.iloc[-1] + pd.Timedelta(days=1), periods=horizon))
        # top_k=1 keeps only the most likely token at every step: greedy, no sampling noise
        pred = self._predictor.predict(
            df=x, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=horizon,
            T=1.0, top_k=1, top_p=1.0, sample_count=1, verbose=False,
        )
        return pred["close"].to_numpy(float)
