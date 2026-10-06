import pandas as pd
import pytest

from bench.config import Asset
from bench.data import (
    COLUMNS, load_prices, merge_candles, normalize, stale_assets, update_prices,
)
from tests.helpers import candles


def raw_frame():
    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-06"], tz="America/New_York")
    return pd.DataFrame(
        {"Open": [100.0, 101.0, 102.0], "High": [103.0, 104.0, 105.0],
         "Low": [99.0, 100.0, 101.0], "Close": [102.0, 103.0, 104.0],
         "Volume": [10, 11, 12]},
        index=idx,
    )


def test_normalize_uses_local_session_date_and_dedups():
    df = normalize(raw_frame())
    assert list(df.columns) == COLUMNS
    assert df["date"].tolist() == ["2026-01-05", "2026-01-06"]
    assert df["close"].tolist() == [102.0, 104.0]  # duplicate date keeps the last row


def test_normalize_drops_nan_and_nonpositive_rows():
    raw = raw_frame()
    raw.iloc[0, raw.columns.get_loc("Close")] = float("nan")
    raw.iloc[1, raw.columns.get_loc("Open")] = 0.0
    assert normalize(raw)["date"].tolist() == ["2026-01-06"]


def test_normalize_empty():
    assert list(normalize(pd.DataFrame()).columns) == COLUMNS


def test_merge_new_overrides_old_and_sorts():
    old = candles([("2026-01-05", 1, 1, 1, 1), ("2026-01-06", 2, 2, 2, 2)])
    new = candles([("2026-01-06", 9, 9, 9, 9), ("2026-01-07", 3, 3, 3, 3)])
    out = merge_candles(old, new)
    assert out["date"].tolist() == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert out["close"].tolist() == [1, 9, 3]


ASSETS = [Asset("AAA", "stock", 5), Asset("BBB", "crypto", 2)]


def test_update_first_fetch_uses_start_then_overlap(tmp_path):
    calls = []

    def fake(symbol, since):
        calls.append((symbol, since))
        return candles([("2026-01-05", 1, 1, 1, 1), ("2026-01-06", 2, 2, 2, 2)])

    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=fake)
    assert status == {"AAA": "ok", "BBB": "ok"}
    assert calls[0] == ("AAA", "2019-01-01")
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=fake)
    assert calls[2] == ("AAA", "2025-12-27")  # last date minus 10 days


def test_update_failure_keeps_cache(tmp_path):
    good = lambda s, since: candles([("2026-01-05", 1, 1, 1, 1)])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=good)
    before = (tmp_path / "AAA.csv").read_text()

    def boom(symbol, since):
        raise RuntimeError("rate limited")

    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=boom)
    assert status["AAA"].startswith("error: RuntimeError")
    assert (tmp_path / "AAA.csv").read_text() == before


def test_update_empty_fetch_is_an_error_not_a_wipe(tmp_path):
    good = lambda s, since: candles([("2026-01-05", 1, 1, 1, 1)])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=good)
    before = (tmp_path / "AAA.csv").read_text()
    empty = lambda s, since: pd.DataFrame(columns=COLUMNS)
    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=empty)
    assert "no rows" in status["AAA"]
    assert (tmp_path / "AAA.csv").read_text() == before


def test_load_prices_missing_file_is_empty(tmp_path):
    out = load_prices(tmp_path, ASSETS)
    assert len(out["AAA"]) == 0 and list(out["AAA"].columns) == COLUMNS


def test_stale_assets():
    prices = {
        "AAA": candles([("2026-01-01", 1, 1, 1, 1)]),  # 9 days behind cutoff 01-10
        "BBB": candles([("2026-01-07", 1, 1, 1, 1)]),  # 3 days behind, crypto limit 2
        "CCC": candles([("2026-01-10", 1, 1, 1, 1)]),  # fresh
    }
    assets = [Asset("AAA", "stock", 5), Asset("BBB", "crypto", 2), Asset("CCC", "stock", 5),
              Asset("DDD", "stock", 5)]
    out = stale_assets(prices, assets, "2026-01-11")
    assert out == {"AAA": 9, "BBB": 3, "DDD": None}
