import hashlib
from datetime import date, timedelta

import numpy as np
import torch
from torch import nn

from estimators.base import Estimator, Prediction

SEQ = 20          # days in each input window
SCALE = 50.0      # targets are scaled so typical daily returns are near 1
EPOCHS = 8
MIN_ROWS = SEQ + 50

_MEMO = {}  # at most one entry: (training boundary, digest of the training data) -> state dict


def _boundary(asof):
    """The Monday of the week containing `asof` (or `asof` itself on a Monday), as an ISO date.

    The model used for a prediction is trained only on candles dated on or before this boundary,
    which is never later than `asof`: a replay can therefore never use a model that saw the future,
    and a live run on any weekday reproduces exactly the model the Monday run would have trained.
    """
    d = date.fromisoformat(asof)
    return (d - timedelta(days=d.weekday())).isoformat()


def _features(df):
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    ret = np.concatenate([[0.0], c[1:] / c[:-1] - 1.0])
    f = np.column_stack([ret, (h - l) / c, (c - o) / o]) / 0.02
    return np.clip(f, -10, 10)


def _windows(df):
    f, c = _features(df), df["close"].to_numpy(float)
    idx = range(SEQ, len(df) - 1)  # the window ends at day i, the target is day i -> i+1
    xs = np.stack([f[i - SEQ + 1 : i + 1] for i in idx])
    ys = np.array([c[i + 1] / c[i] - 1.0 for i in idx]) * SCALE
    return xs, ys


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(3, 32, batch_first=True)
        self.head = nn.Linear(32, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1]).squeeze(-1)


def _train(X, Y):
    """Deterministic: fixed seeds, one thread, deterministic kernels. Restores the global torch state."""
    threads, det = torch.get_num_threads(), torch.are_deterministic_algorithms_enabled()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    try:
        torch.manual_seed(0)
        Xt, Yt = torch.tensor(X, dtype=torch.float32), torch.tensor(Y, dtype=torch.float32)
        net = Net()
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        gen = torch.Generator().manual_seed(0)
        for _ in range(EPOCHS):
            perm = torch.randperm(len(Xt), generator=gen)
            for i in range(0, len(Xt), 256):
                batch = perm[i : i + 256]
                opt.zero_grad()
                nn.functional.mse_loss(net(Xt[batch]), Yt[batch]).backward()
                opt.step()
        return net
    finally:
        torch.use_deterministic_algorithms(det)
        torch.set_num_threads(threads)


def _model(history, asof):
    """The weekly model for `asof`: trained on candles dated <= the week's Monday, pooled across assets.

    A pure function of (boundary, the history up to the boundary), so it is identical in a one-year
    replay, in a live run and when called twice. It is kept only in memory for the life of the
    process (the CI cache is never re-saved, so a model file could not be shared anyway).
    """
    boundary = _boundary(asof)
    parts = []
    for df in history.values():
        cut = df[df["date"] <= boundary]
        if len(cut) >= MIN_ROWS:
            parts.append(_windows(cut.reset_index(drop=True)))
    if not parts:
        return None
    X = np.concatenate([p[0] for p in parts])
    Y = np.concatenate([p[1] for p in parts])
    key = (boundary, hashlib.sha256(X.tobytes() + Y.tobytes()).hexdigest())
    if key not in _MEMO:
        _MEMO.clear()
        _MEMO[key] = _train(X, Y)
    return _MEMO[key]


class Lstm(Estimator):
    """A small LSTM on 20-day windows of return, range and body, pooled across assets.

    Retrained weekly: the model for any day is trained on the candles up to the Monday of that
    week and nothing later (no look-ahead, deterministic), then applied to the latest 20 candles
    of each asset. No file is cached between runs.
    """

    name = "lstm"

    def predict(self, history, assets):
        usable = {a: df for a, df in history.items() if len(df) >= MIN_ROWS}
        if not usable:
            return {}
        asof = max(df["date"].iloc[-1] for df in usable.values())
        net = _model(usable, asof)
        if net is None:
            return {}
        net.eval()
        out = {}
        with torch.no_grad():
            for a in assets:
                if a in usable:
                    x = torch.tensor(_features(usable[a])[-SEQ:][None], dtype=torch.float32)
                    out[a] = Prediction(float(net(x)[0]) / SCALE)
        return out
