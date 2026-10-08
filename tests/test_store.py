import pytest

from bench.store import EQUITY_COLS, SchemaMismatch, Store


def test_prediction_roundtrip(tmp_path):
    s = Store(tmp_path / "live")
    payload = {"predictions": {"AAA": {"asof": "2026-01-02", "expected_return": 0.01}}}
    s.save_prediction("est", "2026-01-03", payload)
    assert s.load_predictions("est") == {"2026-01-03": payload}


def test_empty_loads_have_columns(tmp_path):
    s = Store(tmp_path / "live")
    eq = s.load_equity("est")
    assert list(eq.columns) == EQUITY_COLS and len(eq) == 0


def test_append_accumulates(tmp_path):
    s = Store(tmp_path / "live")
    row = {"date": "2026-01-05", "equity": 10100.0, "day_return": 0.01, "n_universe": 2, "n_traded": 1}
    s.append_equity("est", [row])
    s.append_equity("est", [{**row, "date": "2026-01-06"}])
    eq = s.load_equity("est")
    assert eq["date"].tolist() == ["2026-01-05", "2026-01-06"]


def test_runs_log(tmp_path):
    s = Store(tmp_path / "live")
    s.record_run("est", {"run_date": "2026-01-03", "status": "ok"})
    s.record_run("est", {"run_date": "2026-01-04", "status": "failed"})
    assert [r["status"] for r in s.load_runs("est")] == ["ok", "failed"]


def test_schema_mismatch_raises(tmp_path):
    root = tmp_path / "live"
    Store(root)
    (root / "SCHEMA").write_text("99\n")
    with pytest.raises(SchemaMismatch):
        Store(root)


def test_account_round_trip_with_missing_cells(tmp_path):
    from bench.strategies.common import EQUITY_COLS, LEDGER_COLS, Result

    st = Store(tmp_path)
    led = {c: None for c in LEDGER_COLS}
    led.update(date="2026-01-06", asset="AAA", asof="2026-01-05", traded=1, net_ret=0.01)
    eq = {"date": "2026-01-06", "equity": 10100.0, "day_return": 0.01, "n_universe": 1, "n_traded": 1, "n_open": 0}
    st.write_account("m", "hold", Result([led], [eq], [{"asset": "AAA"}]))
    e, l = st.load_account("m", "hold")
    assert list(e.columns) == EQUITY_COLS and list(l.columns) == LEDGER_COLS
    assert l["date"].tolist() == ["2026-01-06"] and l["hit"].isna().all()
    assert st.load_positions("m", "hold") == [{"asset": "AAA"}]
    st.write_account("m", "hold", Result([], [], []))
    assert not (tmp_path / "accounts" / "m").exists()
