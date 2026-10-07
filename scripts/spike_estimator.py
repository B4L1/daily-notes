import sys
import time

from bench.config import load_config
from bench.data import load_prices
from estimators import registry

name = sys.argv[1]
settings, assets = load_config("assets.yaml")
prices = load_prices("data/prices", assets)
hist = {s: prices[s].iloc[-400:].reset_index(drop=True) for s in ("SPY", "BTC-USD")}
est = registry.build(name)
t0 = time.time()
out = est.predict(hist, list(hist))
dt = time.time() - t0
print(out)
per_asset = dt / len(hist)
print(f"{dt:.1f}s for {len(hist)} assets = {per_asset:.1f}s per asset (includes model load)")
print(f"daily run for {len(assets)} assets: about {per_asset * len(assets) / 60:.1f} min on this machine")
print(f"one-year backfill at stride 1: about {per_asset * len(assets) * 365 / 3600:.1f} h on this machine")
