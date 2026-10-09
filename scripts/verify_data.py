import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.config import load_config
from bench.data import load_prices
from bench.store import Store

ACCOUNT_NUMERIC = ["entry", "exit", "expected_return", "net_ret", "weight", "cost", "actual_cc"]
CANDLE_STRATEGIES = ("one_day", "one_day_short", "top_picks")


def _finite(df, cols):
    return bool(np.isfinite(df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)).all())


def check(data_dir="data", assets_file="assets.yaml"):
    settings, assets = load_config(assets_file)
    prices = load_prices(Path(data_dir) / "prices", assets)
    problems = []
    frames = [df[["date", "open", "close"]].assign(asset=sym) for sym, df in prices.items() if df is not None and len(df)]
    refs = pd.concat(frames).drop_duplicates(["asset", "date"]) if frames else pd.DataFrame(columns=["date", "open", "close", "asset"])
    for sym, df in prices.items():
        if df is not None and len(df) and (df["date"].duplicated().any() or not df["date"].is_monotonic_increasing):
            problems.append(f"prices/{sym}: dates are not unique and increasing")
    for mode in ("live", "backtest"):
        root = Path(data_dir) / mode
        if not (root / "estimators").exists():
            continue
        store = Store(root)
        crypto = {a.symbol for a in assets if a.group == "crypto"}
        for name in sorted(p.name for p in (root / "estimators").iterdir() if p.is_dir()):
            where = f"{mode}/{name}"
            for run_date, payload in store.load_predictions(name).items():
                day_before = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
                for asset, p in payload["predictions"].items():
                    if not p["asof"] < run_date:
                        problems.append(f"{where}/{run_date}/{asset}: asof {p['asof']} is not before the run date")
                    elif asset in crypto and p["asof"] != day_before:
                        problems.append(f"{where}/{run_date}/{asset}: crypto asof {p['asof']} is not the day before the run (retroactive prediction)")
        acct_root = root / "accounts"
        for model_dir in sorted(p for p in acct_root.iterdir() if p.is_dir()) if acct_root.exists() else []:
            for strat_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
                where = f"{mode}/{model_dir.name}/{strat_dir.name}"
                eq, led = store.load_account(model_dir.name, strat_dir.name)
                if eq.empty or led.empty:
                    problems.append(f"{where}: account files are empty")
                    continue
                if not _finite(eq, list(eq.columns.drop("date"))):
                    problems.append(f"{where}: equity.csv has missing or non-finite values")
                    continue
                # a hold position sold because the model made no prediction has no expected return
                forced = (led["action"] == "close") & led["asof"].isna()
                rest = [c for c in ACCOUNT_NUMERIC if c != "expected_return"]
                if not _finite(led, rest) or not _finite(led[~forced], ["expected_return"]):
                    problems.append(f"{where}: ledger.csv has missing or non-finite values")
                    continue
                if eq["date"].duplicated().any() or not eq["date"].is_monotonic_increasing:
                    problems.append(f"{where}: settled dates are not unique and increasing")
                expected = settings.start_equity * (1 + eq["day_return"]).cumprod()
                if (expected - eq["equity"]).abs().max() > 1e-6:
                    problems.append(f"{where}: equity does not compound from day returns")
                per_day = (led["net_ret"] * led["weight"]).groupby(led["date"]).sum()
                want = (per_day / eq.set_index("date")["n_universe"]).clip(lower=-1.0)
                got = eq.set_index("date")["day_return"]
                if set(per_day.index) != set(got.index) or (want - got).abs().max() > 1e-9:
                    problems.append(f"{where}: day returns do not follow from the ledger")
                if strat_dir.name in CANDLE_STRATEGIES:
                    m = led.merge(refs, on=["asset", "date"], how="left", suffixes=("", "_c"))
                    bad = m["open"].isna() | ((m["open"] - m["entry"]).abs() > 1e-9) | ((m["close"] - m["exit"]).abs() > 1e-9)
                    for r in m[bad].itertuples():
                        problems.append(f"{where}: ledger row {r.asset} {r.date} does not match the cached candle (entry/exit vs data/prices open/close; prices were re-based or the candle was incomplete)")
    return problems


if __name__ == "__main__":
    found = check(sys.argv[1] if len(sys.argv) > 1 else "data")
    print("\n".join(found) if found else "data checks passed")
    sys.exit(1 if found else 0)
