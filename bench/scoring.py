import math

import numpy as np


def total_return(equities, start):
    return equities[-1] / start - 1.0 if equities else 0.0


def max_drawdown(equities):
    peak, worst = -math.inf, 0.0
    for e in equities:
        peak = max(peak, e)
        worst = min(worst, e / peak - 1.0)
    return worst


def worst_day(day_returns):
    return min(day_returns) if day_returns else 0.0


def hit_rate(flags):
    kept = [f for f in flags if f is not None and f == f]
    return sum(kept) / len(kept) if kept else None


def sign_flip_pvalue(diffs, n_iter=5000, seed=0):
    """One-sided: how often random sign flips give a mean at least as large as observed."""
    d = np.asarray(diffs, dtype=float)
    if len(d) < 2 or not d.any():
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_iter, len(d)))
    perm = (signs * d).mean(axis=1)
    return float((np.sum(perm >= d.mean()) + 1) / (n_iter + 1))


def edge_vs_control(est, control):
    common = sorted(set(est) & set(control))
    diffs = [est[d] - control[d] for d in common]
    return {
        "n": len(common),
        "edge": float(np.mean(diffs)) if diffs else 0.0,
        "p_value": sign_flip_pvalue(diffs),
    }


def sanity_flag(day_returns, day_pct, week_pct):
    """Gains this large are far more likely a bug or a data leak than skill."""
    if not day_returns:
        return False
    if day_returns[-1] > day_pct:
        return True
    week = 1.0
    for r in day_returns[-7:]:
        week *= 1.0 + r
    return week - 1.0 > week_pct
