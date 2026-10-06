import pandas as pd

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


def test_update_atomic_write_cleans_up_on_failure(tmp_path, monkeypatch):
    """Simulate write failure mid-operation: cache should be untouched and no temp file left."""
    good = lambda s, since: candles([("2026-01-05", 1, 1, 1, 1)])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=good)
    before = (tmp_path / "AAA.csv").read_text()

    # Monkeypatch to_csv to succeed (create temp file) but raise on flush
    orig_to_csv = pd.DataFrame.to_csv
    write_count = [0]

    def failing_to_csv(self, path, *args, **kwargs):
        write_count[0] += 1
        if write_count[0] == 1:  # First call (AAA) fails mid-write
            # Create the file to simulate partial write, then raise
            with open(path, "w") as f:
                f.write("corrupted")
            raise OSError("simulated disk failure")
        return orig_to_csv(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_csv", failing_to_csv)

    status = update_prices(tmp_path, ASSETS, "2019-01-01", fetch=good)
    # First asset (AAA) should error, cache unchanged, no temp file
    assert "error: OSError" in status["AAA"]
    assert (tmp_path / "AAA.csv").read_text() == before
    # No stray temp files (*.tmp pattern)
    import glob
    assert len(glob.glob(str(tmp_path / ".*.tmp"))) == 0


def test_update_corrupt_cache_does_not_stop_other_assets(tmp_path):
    """One asset with corrupt CSV reports error; other assets still update."""
    assets = [Asset("AAA", "stock", 5), Asset("BBB", "stock", 5)]

    # Write garbage into AAA's cache
    (tmp_path / "AAA.csv").write_text("this is not a valid CSV\ninvalid data here\n")

    def fake(symbol, since):
        return candles([("2026-01-05", 1, 1, 1, 1)])

    status = update_prices(tmp_path, assets, "2019-01-01", fetch=fake)
    # AAA should error (corrupt cache read)
    assert status["AAA"].startswith("error:")
    # BBB should succeed (independent asset)
    assert status["BBB"] == "ok"
    # BBB file should be written, AAA file should remain corrupt
    assert (tmp_path / "BBB.csv").exists()
    assert (tmp_path / "AAA.csv").read_text() == "this is not a valid CSV\ninvalid data here\n"
