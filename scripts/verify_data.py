import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.config import load_config
from bench.data import load_prices
from bench.store import Store

LEDGER_NUMERIC = ["entry", "exit", "expected_return", "gross_ret", "net_ret", "actual_cc"]


def _finite(df, cols):
    return bool(np.isfinite(df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)).all())


def check(data_dir="data", assets_file="assets.yaml"):
    settings, assets = load_config(assets_file)
    prices = load_prices(Path(data_dir) / "prices", assets)
    problems = []
    for sym, df in prices.items():
        if df is not None and len(df) and (df["date"].duplicated().any() or not df["date"].is_monotonic_increasing):
            problems.append(f"prices/{sym}: dates are not unique and increasing")
    for mode in ("live", "backtest"):
        root = Path(data_dir) / mode
        if not (root / "estimators").exists():
            continue
        store = Store(root)
        for name in sorted(p.name for p in (root / "estimators").iterdir() if p.is_dir()):
            where = f"{mode}/{name}"
            for run_date, payload in store.load_predictions(name).items():
                for asset, p in payload["predictions"].items():
                    if not p["asof"] < run_date:
                        problems.append(f"{where}/{run_date}/{asset}: asof {p['asof']} is not before the run date")
            eq = pd.DataFrame()  # Task 9: read accounts instead
            if len(eq):
                if not _finite(eq, list(eq.columns.drop("date"))):
                    problems.append(f"{where}: equity.csv has missing or non-finite values")
                    continue_eq = False
                else:
                    continue_eq = True
            else:
                continue_eq = False
            if continue_eq:
                if eq["date"].duplicated().any() or not eq["date"].is_monotonic_increasing:
                    problems.append(f"{where}: settled dates are not unique and increasing")
                expected = settings.start_equity * (1 + eq["day_return"]).cumprod()
                if (expected - eq["equity"]).abs().max() > 1e-6:
                    problems.append(f"{where}: equity does not compound from day returns")
            led = pd.DataFrame()  # Task 9: read accounts instead
            if len(led):
                if not _finite(led, LEDGER_NUMERIC):
                    problems.append(f"{where}: ledger.csv has missing or non-finite values")
                    continue
                refs = pd.concat(
                    [df[["date", "open", "close"]].assign(asset=sym) for sym, df in prices.items() if df is not None and len(df)]
                ).drop_duplicates(["asset", "date"]).rename(columns={"date": "settle_date"})
                m = led.merge(refs, on=["asset", "settle_date"], how="left", suffixes=("", "_c"))
                bad = m["open"].isna() | ((m["open"] - m["entry"]).abs() > 1e-9) | ((m["close"] - m["exit"]).abs() > 1e-9)
                for r in m[bad].itertuples():
                    problems.append(f"{where}: ledger row {r.asset} {r.settle_date} does not match the cached candle (entry/exit vs data/prices open/close; prices were re-based or the candle was incomplete)")
    return problems


if __name__ == "__main__":
    found = check(sys.argv[1] if len(sys.argv) > 1 else "data")
    print("\n".join(found) if found else "data checks passed")
    sys.exit(1 if found else 0)
