import math
from datetime import date, datetime, timedelta, timezone

from bench.broker import settle_estimator
from bench.data import stale_assets
from bench.store import SCHEMA_VERSION

# Worst case: window (11 h) + predict job (up to 45 min) + aggregate/commit (up to 20 min) is about 12h05,
# still before the ~13:30 UTC US open.
LIVE_WINDOW_HOURS = 11


def cutoff_for(run_date):
    return (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()


def cut_history(prices, run_date):
    """Only candles dated before the run date. This is the no-look-ahead guarantee."""
    cutoff = cutoff_for(run_date)
    return {a: df[df["date"] <= cutoff].reset_index(drop=True) for a, df in prices.items()}


def live_window_ok(run_date, now):
    start = datetime.fromisoformat(f"{run_date}T00:00:00+00:00")
    return start <= now <= start + timedelta(hours=LIVE_WINDOW_HOURS)


def assets_needing_prediction(store, name, history, run_date):
    """Assets whose newest candle has not been predicted by an earlier run."""
    earlier = set()
    for rd, payload in store.load_predictions(name).items():
        if rd < run_date:
            for asset, p in payload["predictions"].items():
                earlier.add((asset, p["asof"]))
    return [
        a for a, df in history.items()
        if len(df) and (a, df["date"].iloc[-1]) not in earlier
    ]


def _validate(asset, p):
    if not math.isfinite(p.expected_return):
        raise ValueError(f"non-finite expected_return for {asset}")
    if p.confidence is not None and not math.isfinite(p.confidence):
        raise ValueError(f"non-finite confidence for {asset}")
    if p.path is not None and not all(math.isfinite(x) for x in p.path):
        raise ValueError(f"non-finite path for {asset}")


def run_estimator_day(store, estimator, prices, run_date, settings, now=None, assets=None):
    """Settle everything that can be settled, then predict. Used by live runs and backfill.

    now=None means a backtest replay: the live-window check is skipped.

    Freshness guard: when `assets` is given, an asset whose newest candle at or before the cutoff
    (run_date - 1) is older than its max_gap_days (0 for crypto = exactly the cutoff) is NOT
    predicted and is recorded as `skipped_stale` on the run record. A prediction made for a
    session that may already be complete would be retroactive.
    """
    name = estimator.name
    history = cut_history(prices, run_date)
    settle_estimator(store, name, history, settings)

    rec = {"run_date": run_date, "estimator": name}
    if now is not None and not live_window_ok(run_date, now):
        rec.update(status="skipped_late", error="run started outside the live window")
        store.record_run(name, rec)
        return rec

    stale = stale_assets(prices, assets, run_date) if assets is not None else {}
    skipped = sorted(a for a in stale if len(history.get(a, ())))
    if skipped:
        rec["skipped_stale"] = skipped
    need = [a for a in assets_needing_prediction(store, name, history, run_date) if a not in stale]
    existing = store.load_predictions(name).get(run_date)
    kept = {}
    if existing:
        for asset in need:
            old = existing["predictions"].get(asset)
            if old is not None and old["asof"] == history[asset]["date"].iloc[-1]:
                kept[asset] = old  # already predicted (and possibly scored): never overwrite
    remaining = [a for a in need if a not in kept]
    try:
        raw = estimator.predict(history, list(remaining)) if remaining else {}
        preds = {}
        for asset, p in raw.items():
            if asset not in remaining:
                continue
            _validate(asset, p)
            preds[asset] = {
                "asof": history[asset]["date"].iloc[-1],
                "expected_return": float(p.expected_return),
                "confidence": None if p.confidence is None else float(p.confidence),
                "path": None if p.path is None else [float(x) for x in p.path],
            }
        if existing is None or preds:
            created_at = existing["created_at"] if existing else (
                None if now is None else now.astimezone(timezone.utc).isoformat())
            payload = {
                "schema_version": SCHEMA_VERSION, "estimator": name, "run_date": run_date,
                "created_at": created_at,
                "predictions": {**(existing["predictions"] if existing else {}), **kept, **preds},
            }
            store.save_prediction(name, run_date, payload)
            total = len(payload["predictions"])
        else:
            total = len(existing["predictions"])
        rec.update(status="ok", n_predictions=total)
    except Exception as e:  # an estimator may fail; the bench must not
        rec.update(status="failed", error=f"{type(e).__name__}: {e}")
    store.record_run(name, rec)
    return rec
