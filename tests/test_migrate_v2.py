import pytest

from scripts.migrate_v2 import migrate


def test_migrate_bumps_schema_and_removes_v1_ledgers(tmp_path):
    for mode in ("live", "backtest"):
        d = tmp_path / mode / "estimators" / "m1"
        (d / "predictions").mkdir(parents=True)
        (d / "predictions" / "2026-01-06.json").write_text("{}", encoding="utf-8")
        (d / "equity.csv").write_text("x", encoding="utf-8")
        (d / "ledger.csv").write_text("x", encoding="utf-8")
        (d / "runs.jsonl").write_text("{}\n", encoding="utf-8")
        (tmp_path / mode / "SCHEMA").write_text("1\n", encoding="utf-8")
    done = migrate(tmp_path)
    for mode in ("live", "backtest"):
        d = tmp_path / mode / "estimators" / "m1"
        assert (tmp_path / mode / "SCHEMA").read_text().strip() == "2"
        assert not (d / "equity.csv").exists() and not (d / "ledger.csv").exists()
        assert (d / "predictions" / "2026-01-06.json").exists() and (d / "runs.jsonl").exists()
    assert any("equity.csv" in line for line in done)
    assert migrate(tmp_path) == []  # running it again changes nothing


def test_migrate_refuses_an_unknown_schema(tmp_path):
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "SCHEMA").write_text("7\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="schema 7"):
        migrate(tmp_path)
