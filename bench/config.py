import math
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


GROUPS = ("stock", "etf", "commodity", "crypto")


@dataclass(frozen=True)
class Asset:
    symbol: str
    group: str  # stock | etf | commodity | crypto
    max_gap_days: int  # how many days behind before the asset is reported stale
    cost_round_trip: float = 0.001  # buy and sell, as a fraction of the position
    borrow_annual: float = 0.0  # short borrow, per year


@dataclass(frozen=True)
class Settings:
    start_equity: float = 10000.0
    min_live_days: int = 60
    sanity_day_pct: float = 0.10
    sanity_week_pct: float = 0.50
    history_start: str = "2019-01-01"


def load_config(path="assets.yaml"):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    given = raw.get("settings") or {}
    extra = set(given) - {f.name for f in fields(Settings)}
    if extra:
        raise ValueError(f"unknown settings: {sorted(extra)}")
    assets = [Asset(**a) for a in raw.get("assets", [])]
    for a in assets:
        if a.group not in GROUPS:
            raise ValueError(f"{a.symbol}: unknown group {a.group!r}")
        for field in ("cost_round_trip", "borrow_annual"):
            v = getattr(a, field)
            if not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
                raise ValueError(f"{a.symbol}: bad cost value {field}={v!r}")
    symbols = [a.symbol for a in assets]
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate asset symbols")
    return Settings(**given), assets
