import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.config import load_config
from bench.data import load_prices
from bench.store import Store


def check(data_dir="data", assets_file="assets.yaml"):
    settings, assets = load_config(assets_file)
    prices = load_prices(Path(data_dir) / "prices", assets)
    problems = []
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
            eq = store.load_equity(name)
            if len(eq):
                if eq["date"].duplicated().any() or not eq["date"].is_monotonic_increasing:
                    problems.append(f"{where}: settled dates are not unique and increasing")
                expected = settings.start_equity * (1 + eq["day_return"]).cumprod()
                if (expected - eq["equity"]).abs().max() > 1e-6:
                    problems.append(f"{where}: equity does not compound from day returns")
            for r in store.load_ledger(name).itertuples():
                df = prices.get(r.asset)
                row = df[df["date"] == r.settle_date] if df is not None else []
                if len(row) != 1 or abs(row["open"].iloc[0] - r.entry) > 1e-9 or abs(row["close"].iloc[0] - r.exit) > 1e-9:
                    problems.append(f"{where}: ledger row {r.asset} {r.settle_date} does not match the candle")
                    break
    return problems


if __name__ == "__main__":
    found = check(sys.argv[1] if len(sys.argv) > 1 else "data")
    print("\n".join(found) if found else "data checks passed")
    sys.exit(1 if found else 0)
