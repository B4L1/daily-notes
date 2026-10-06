from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Asset:
    symbol: str
    group: str  # stock | crypto | commodity
    max_gap_days: int  # how many days behind before the asset is reported stale


@dataclass(frozen=True)
class Settings:
    start_equity: float = 10000.0
    cost_round_trip: float = 0.001
    trade_threshold: float = 0.001
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
    symbols = [a.symbol for a in assets]
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate asset symbols")
    return Settings(**given), assets
