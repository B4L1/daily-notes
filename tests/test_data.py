import pandas as pd

from bench.config import Asset
from bench.data import (
    COLUMNS, find_revisions, load_prices, merge_candles, normalize, stale_assets, update_prices,
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


def test_merge_is_append_only_and_sorts():
    old = candles([("2026-01-05", 1, 1, 1, 1), ("2026-01-06", 2, 2, 2, 2)])
    new = candles([("2026-01-06", 9, 9, 9, 9), ("2026-01-07", 3, 3, 3, 3)])
    out = merge_candles(old, new)
    assert out["date"].tolist() == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert out["close"].tolist() == [1, 2, 3]  # the stored 2026-01-06 value is kept


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


def test_normalize_ignores_adj_close_column():
    raw = raw_frame()
    raw["Adj Close"] = [1.0, 1.0, 1.0]
    df = normalize(raw)
    assert df["close"].tolist() == [102.0, 104.0]


def test_fetch_asset_requests_raw_prices(monkeypatch):
    import sys
    import types

    from bench import data

    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kw):
            seen.update(kw)
            return raw_frame()

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    data.fetch_asset("AAA", "2026-01-01")
    assert seen["auto_adjust"] is False


def test_update_never_stores_candles_after_through(tmp_path):
    fake = lambda s, since: candles([
        ("2026-01-05", 1, 1, 1, 1), ("2026-01-06", 2, 2, 2, 2), ("2026-01-07", 3, 3, 3, 3),
    ])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=fake, through="2026-01-06")
    assert load_prices(tmp_path, ASSETS)["AAA"]["date"].tolist() == ["2026-01-05", "2026-01-06"]


def test_update_default_through_excludes_today_utc(tmp_path):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    fake = lambda s, since: candles([("2026-01-05", 1, 1, 1, 1), (today, 2, 2, 2, 2)])
    update_prices(tmp_path, ASSETS, "2019-01-01", fetch=fake)
    assert today not in load_prices(tmp_path, ASSETS)["AAA"]["date"].tolist()


ONE = [Asset("AAA", "stock", 5)]
BASE = [(f"2026-01-{d:02d}", 100 + d, 101 + d, 99 + d, 100.5 + d) for d in range(5, 13)]
THROUGH = "2026-12-31"


def _stored(tmp_path):
    update_prices(tmp_path, ONE, "2019-01-01", fetch=lambda s, since: candles(BASE), through=THROUGH)


def _scaled(rows, factor, from_day=0):
    return [(d, o * f, h * f, l * f, c * f) for (d, o, h, l, c), f in
            zip(rows, [1.0] * from_day + [factor] * (len(rows) - from_day))]


def test_normal_new_day_append_has_no_revisions(tmp_path):
    _stored(tmp_path)
    new = candles(BASE[-3:] + [("2026-01-13", 120, 121, 119, 120.5)])
    status = update_prices(tmp_path, ONE, "2019-01-01", fetch=lambda s, since: new, through=THROUGH)
    assert status["AAA"] == "ok" and status["AAA"].revisions == [] and not status["AAA"].split_like
    out = load_prices(tmp_path, ONE)["AAA"]
    assert out["date"].tolist()[-1] == "2026-01-13" and len(out) == len(BASE) + 1


def test_append_only_keeps_old_values_and_flags_small_revision(tmp_path):
    _stored(tmp_path)
    rev = candles([(d, o, h, l, c) for d, o, h, l, c in BASE[-3:-1]] + [("2026-01-12", 112, 113, 111, 112.0)])
    status = update_prices(tmp_path, ONE, "2019-01-01", fetch=lambda s, since: rev, through=THROUGH)
    st = status["AAA"]
    assert st == "ok" and not st.split_like  # one revised date of three: not split-like
    assert [r["date"] for r in st.revisions] == ["2026-01-12"]
    out = load_prices(tmp_path, ONE)["AAA"]
    assert out["close"].tolist() == [c for *_, c in BASE]  # old stored values kept


def test_tiny_float_noise_is_not_a_revision():
    old = candles([("2026-01-05", 100.0, 101.0, 99.0, 100.5)])
    new = candles([("2026-01-05", 100.0 * (1 + 1e-8), 101.0, 99.0, 100.5)])
    assert find_revisions(old, new)[0] == []


def test_split_like_revision_is_detected_and_old_values_kept(tmp_path):
    _stored(tmp_path)
    split = candles(_scaled(BASE[-4:], 0.5))
    status = update_prices(tmp_path, ONE, "2019-01-01", fetch=lambda s, since: split, through=THROUGH)
    st = status["AAA"]
    assert st.split_like and abs(st.ratio - 0.5) < 1e-9 and st.overlap_days == 4
    assert load_prices(tmp_path, ONE)["AAA"]["close"].tolist() == [c for *_, c in BASE]


def test_constant_but_small_ratio_is_not_split_like():
    old = candles(BASE[-4:])
    new = candles(_scaled(BASE[-4:], 1.005))
    revisions, split_like, ratio, n = find_revisions(old, new)
    assert revisions and not split_like and n == 4


def test_cli_fetch_warns_and_exits_nonzero_only_for_split(tmp_path, monkeypatch, capsys):
    import yaml
    from bench import cli
    from bench import data as data_mod
    from datetime import datetime, timezone

    assets_file = tmp_path / "assets.yaml"
    assets_file.write_text(yaml.safe_dump({
        "settings": {"history_start": "2019-01-01"},
        "assets": [{"symbol": "AAA", "group": "stock", "max_gap_days": 5}],
    }), encoding="utf-8")
    monkeypatch.setenv("BENCH_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("BENCH_ASSETS", str(assets_file))
    now = datetime(2026, 2, 1, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(cli, "update_prices", lambda *a, **k: data_mod.update_prices(*a, **{**k, "fetch": lambda s, since: candles(BASE)}))
    assert cli.main(["fetch"], now=now) == 0
    small = candles(_scaled(BASE[-4:], 1.0) [:-1] + [("2026-01-12", 112, 113, 111, 112.0)])
    monkeypatch.setattr(cli, "update_prices", lambda *a, **k: data_mod.update_prices(*a, **{**k, "fetch": lambda s, since: small}))
    assert cli.main(["fetch"], now=now) == 0
    out = capsys.readouterr().out
    assert "WARNING: AAA" in out and "2026-01-12" in out and "possible split" not in out
    split = candles(_scaled(BASE[-4:], 0.5))
    monkeypatch.setattr(cli, "update_prices", lambda *a, **k: data_mod.update_prices(*a, **{**k, "fetch": lambda s, since: split}))
    assert cli.main(["fetch"], now=now) == 1
    assert "possible split: manual re-base needed" in capsys.readouterr().out
