import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bench import scoring
from bench.data import stale_assets
from bench.store import SCHEMA_VERSION, Store
from estimators.registry import REGISTRY

CONTROL_RANDOM = "control_random"
PUBLIC_META_SKIP = ("target", "requirements")


def _records(df):
    return json.loads(df.to_json(orient="records"))


def _default(o):
    return o.item() if hasattr(o, "item") else str(o)


def _status_for(runs, run_date):
    todays = [r for r in runs if r.get("run_date") == run_date]
    return todays[-1]["status"] if todays else "no_run"


def _hold_curve(prices, dates, start_equity):
    """Equal-weight close-to-close buy and hold, no costs. A reference line, not an account."""
    per_date = {}
    for df in prices.values():
        d, c = df["date"].tolist(), df["close"].tolist()
        for i in range(1, len(d)):
            per_date.setdefault(d[i], []).append(c[i] / c[i - 1] - 1.0)
    eq, out = float(start_equity), []
    for day in dates:
        rets = per_date.get(day)
        if rets:
            eq *= 1.0 + sum(rets) / len(rets)
        out.append([day, round(eq, 2)])
    return out


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
    trades_by_date = {d: g for d, g in led.groupby("settle_date")}
    days = []
    for rec in _records(eq):
        g = trades_by_date.get(rec["date"])
        trades = [] if g is None else _records(g.drop(columns=["settle_date"]))
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


def _mode_block(data_dir, mode, prices, settings, run_date):
    store = Store(Path(data_dir) / mode)
    eqs = {n: store.load_equity(n) for n in REGISTRY}
    leds = {n: store.load_ledger(n) for n in REGISTRY}
    runs = {n: store.load_runs(n) for n in REGISTRY}
    dates = sorted({d for eq in eqs.values() for d in eq["date"]})
    rand = dict(zip(eqs[CONTROL_RANDOM]["date"], eqs[CONTROL_RANDOM]["day_return"]))
    rows, pnl, hit, equity = {}, {}, {}, {}
    for n in REGISTRY:
        rows[n] = _row(eqs[n], leds[n], runs[n], settings, rand, run_date)
        by_date = dict(zip(eqs[n]["date"], eqs[n]["day_return"]))
        pnl[n] = [by_date.get(d) for d in dates]
        scored = leds[n].dropna(subset=["hit"])
        hits = {} if scored.empty else scored.groupby("settle_date")["hit"].mean().to_dict()
        hit[n] = [hits.get(d) for d in dates]
        equity[n] = [[d, round(float(e), 2)] for d, e in zip(eqs[n]["date"], eqs[n]["equity"])]
    block = {
        "dates": dates, "rows": rows, "pnl": pnl, "hit": hit, "equity": equity,
        "hold": _hold_curve(prices, dates, settings.start_equity),
    }
    return block, eqs, leds


def build_all(data_dir, out_dir, prices, settings, assets, run_date, generated_at=None):
    out = Path(out_dir)
    (out / "estimators").mkdir(parents=True, exist_ok=True)
    meta = [
        {"name": n, **{k: v for k, v in m.items() if k not in PUBLIC_META_SKIP}}
        for n, m in REGISTRY.items()
    ]
    meta_by_name = {m["name"]: m for m in meta}
    details = {
        n: {"schema_version": SCHEMA_VERSION, "name": n, "meta": meta_by_name[n], "modes": {}}
        for n in REGISTRY
    }
    modes = {}
    for mode in ("live", "backtest"):
        block, eqs, leds = _mode_block(data_dir, mode, prices, settings, run_date)
        modes[mode] = block
        for n in REGISTRY:
            details[n]["modes"][mode] = _detail(eqs[n], leds[n], block["rows"][n])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_date": run_date,
        "stale_assets": stale_assets(prices, assets, run_date),
        "estimators": meta,
        "modes": modes,
    }
    (out / "summary.json").write_text(json.dumps(summary, default=_default), encoding="utf-8")
    for n, d in details.items():
        (out / "estimators" / f"{n}.json").write_text(json.dumps(d, default=_default), encoding="utf-8")
