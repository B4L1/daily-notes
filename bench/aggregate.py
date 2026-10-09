import json
import math
from datetime import datetime, timezone
from pathlib import Path

from bench import ensemble, scoring
from bench.data import stale_assets
from bench.scorer import models as all_models
from bench.store import SCHEMA_VERSION, Store
from bench.strategies import STRATEGIES
from estimators.registry import REGISTRY

MAIN = "one_day"
CONTROL_RANDOM = "control_random"
CONTROL_LONG = "control_always_long"
PUBLIC_META_SKIP = ("target", "requirements")


def _records(df):
    return json.loads(df.to_json(orient="records"))


def _default(o):
    return o.item() if hasattr(o, "item") else str(o)


def _status_for(runs, run_date):
    todays = [r for r in runs if r.get("run_date") == run_date]
    return todays[-1]["status"] if todays else "no_run"


def _ticker(prices, assets):
    """Last completed day's close-to-close move per asset (raw prices). Ordering is left to the client."""
    out = []
    for a in assets:
        df = prices.get(a.symbol)
        if df is None or len(df) < 2:
            continue
        prev, cur = float(df["close"].iloc[-2]), float(df["close"].iloc[-1])
        if not (prev > 0 and cur > 0 and math.isfinite(prev) and math.isfinite(cur)):
            continue
        out.append({
            "symbol": a.symbol, "label": a.symbol, "close": round(cur, 4),
            "change_pct": round((cur / prev - 1.0) * 100.0, 4), "date": str(df["date"].iloc[-1]),
        })
    return out


def _skipped_stale(runs, run_date):
    todays = [r for r in runs if r.get("run_date") == run_date]
    return list(todays[-1].get("skipped_stale") or []) if todays else []


def _row(eq, led, runs, settings, rand, run_date):
    n_days = len(eq)
    equities, rets = eq["equity"].tolist(), eq["day_return"].tolist()
    balance = equities[-1] if n_days else float(settings.start_equity)
    prev = equities[-2] if n_days > 1 else float(settings.start_equity)
    calls = led["hit"].dropna().tolist()
    down = led.loc[led["expected_return"] < 0, "hit"].dropna().tolist()
    edge = scoring.edge_vs_control(dict(zip(eq["date"], rets)), rand)
    return {
        "status": _status_for(runs, run_date),
        "skipped_stale": _skipped_stale(runs, run_date),
        "balance": round(balance, 2),
        "day_return": rets[-1] if n_days else None,
        "day_change": round(balance - prev, 2) if n_days else 0.0,
        "spark": [round(e, 2) for e in equities[-30:]],
        "total_return": scoring.total_return(equities, settings.start_equity),
        "max_drawdown": scoring.max_drawdown(equities),
        "worst_day": scoring.worst_day(rets),
        "hit_rate": scoring.hit_rate(calls),
        "hit_rate_down": scoring.hit_rate(down),
        "n_days": n_days,
        "trades_per_day": float(eq["n_traded"].sum()) / n_days if n_days else 0.0,
        "edge": edge["edge"],
        "p_value": edge["p_value"],
        "too_early": n_days < settings.min_live_days,
        "sanity": scoring.sanity_flag(rets, settings.sanity_day_pct, settings.sanity_week_pct),
    }


def _detail(eq, led, row):
    trades_by_date = {d: g for d, g in led.groupby("date")}
    days = []
    for rec in _records(eq):
        g = trades_by_date.get(rec["date"])
        trades = [] if g is None else _records(g.drop(columns=["date"]))
        days.append({**rec, "trades": trades})
    per_asset = {}
    for asset, g in led.groupby("asset"):
        per_asset[asset] = {
            "n": int(len(g)), "traded": int(g["traded"].sum()),
            "hit_rate": scoring.hit_rate(g["hit"].dropna().tolist()),
            "net_return_sum": float(g["net_ret"].sum()),
        }
    equity = [[d, round(float(e), 2)] for d, e in zip(eq["date"], eq["equity"])]
    return {"stats": row, "equity": equity, "days": days, "per_asset": per_asset}


def _series(eq):
    return [[d, round(float(e), 2)] for d, e in zip(eq["date"], eq["equity"])]


def _groups(led):
    """Per asset category: fee-paying trades, summed weighted net return, 1-day hit rate."""
    out = {}
    if led.empty:
        return out
    fee = led[led["action"].isin(["day", "open", "close"]) & (led["traded"] == 1)]
    for group, g in led.groupby("group"):
        out[group] = {
            "trades": int((fee["group"] == group).sum()),
            "net_sum": float((g["net_ret"] * g["weight"]).sum()),
            "hit_rate": scoring.hit_rate(g["hit"].dropna().tolist()),
        }
    return out


def _runs(store, name, run_date):
    """The ensemble is derived, so it has no run log: it ran if it has predictions for the run date."""
    if name != ensemble.NAME:
        return store.load_runs(name)
    return [{"run_date": run_date, "status": "ok"}] if run_date in store.load_predictions(name) else []


def _mode_block(data_dir, mode, settings, run_date):
    store = Store(Path(data_dir) / mode)
    names = all_models(REGISTRY)
    accts = {(n, s): store.load_account(n, s) for n in names for s in STRATEGIES}
    runs = {n: _runs(store, n, run_date) for n in names}
    eqs = {n: accts[(n, MAIN)][0] for n in names}
    leds = {n: accts[(n, MAIN)][1] for n in names}
    dates = sorted({d for eq in eqs.values() for d in eq["date"]})

    def rand(strategy):
        eq = accts[(CONTROL_RANDOM, strategy)][0]
        return dict(zip(eq["date"], eq["day_return"]))

    rows, pnl, hit, equity = {}, {}, {}, {}
    for n in names:
        rows[n] = _row(eqs[n], leds[n], runs[n], settings, rand(MAIN), run_date)
        by_date = dict(zip(eqs[n]["date"], eqs[n]["day_return"]))
        pnl[n] = [by_date.get(d) for d in dates]
        scored = leds[n].dropna(subset=["hit"])
        hits = {} if scored.empty else scored.groupby("date")["hit"].mean().to_dict()
        hit[n] = [hits.get(d) for d in dates]
        equity[n] = _series(eqs[n])
    accounts, extra = {}, {}
    for s in STRATEGIES:
        for n in names:
            eq, led = accts[(n, s)]
            if eq.empty:
                continue
            row = _row(eq, led, runs[n], settings, rand(s), run_date)
            row["groups"] = _groups(led)
            row["hit_rate_5d"] = scoring.hit_rate(led["hit5"].dropna().tolist())
            accounts.setdefault(s, {})[n] = row
            extra[(n, s)] = {"stats": row, "equity": _series(eq), "positions": store.load_positions(n, s)}
    block = {
        "dates": dates, "rows": rows, "pnl": pnl, "hit": hit, "equity": equity,
        "hold": _series(accts[(CONTROL_LONG, "hold")][0]),
        "accounts": accounts,
    }
    return block, eqs, leds, extra


def build_all(data_dir, out_dir, prices, settings, assets, run_date, generated_at=None):
    out = Path(out_dir)
    (out / "estimators").mkdir(parents=True, exist_ok=True)
    meta = [
        {"name": n, "backfill_stride": 1, **{k: v for k, v in m.items() if k not in PUBLIC_META_SKIP}}
        for n, m in REGISTRY.items()
    ]
    meta.append({"name": ensemble.NAME, "backfill_stride": 1, **ensemble.META})
    meta_by_name = {m["name"]: m for m in meta}
    names = [m["name"] for m in meta]
    details = {
        n: {"schema_version": SCHEMA_VERSION, "name": n, "meta": meta_by_name[n], "modes": {}}
        for n in names
    }
    modes = {}
    for mode in ("live", "backtest"):
        block, eqs, leds, extra = _mode_block(data_dir, mode, settings, run_date)
        modes[mode] = block
        for n in names:
            d = _detail(eqs[n], leds[n], block["rows"][n])
            d["accounts"] = {s: extra[(n, s)] for s in STRATEGIES if (n, s) in extra}
            details[n]["modes"][mode] = d
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_date": run_date,
        "stale_assets": stale_assets(prices, assets, run_date),
        "estimators": meta,
        "strategies": list(STRATEGIES),
        "modes": modes,
        "ticker": _ticker(prices, assets),
    }
    (out / "summary.json").write_text(json.dumps(summary, default=_default, allow_nan=False), encoding="utf-8")
    for n, d in details.items():
        (out / "estimators" / f"{n}.json").write_text(json.dumps(d, default=_default, allow_nan=False), encoding="utf-8")
