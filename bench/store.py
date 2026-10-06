import json
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = 1
EQUITY_COLS = ["date", "equity", "day_return", "n_universe", "n_traded"]
LEDGER_COLS = [
    "settle_date", "asset", "asof", "entry", "exit", "expected_return",
    "traded", "gross_ret", "net_ret", "actual_cc", "hit",
]


class SchemaMismatch(RuntimeError):
    pass


class Store:
    """All files for one data set (live or backtest) under one root folder."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / "SCHEMA"
        if marker.exists():
            found = int(marker.read_text().strip())
            if found != SCHEMA_VERSION:
                raise SchemaMismatch(
                    f"{self.root} has schema {found}, code expects {SCHEMA_VERSION}"
                )
        else:
            marker.write_text(f"{SCHEMA_VERSION}\n")

    def est_dir(self, name):
        p = self.root / "estimators" / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_prediction(self, name, run_date, payload):
        d = self.est_dir(name) / "predictions"
        d.mkdir(exist_ok=True)
        text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
        (d / f"{run_date}.json").write_text(text, encoding="utf-8")

    def load_predictions(self, name):
        d = self.est_dir(name) / "predictions"
        out = {}
        for f in sorted(d.glob("*.json")):
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        return out

    def load_equity(self, name):
        return self._load(name, "equity.csv", EQUITY_COLS)

    def load_ledger(self, name):
        return self._load(name, "ledger.csv", LEDGER_COLS)

    def append_equity(self, name, rows):
        self._append(name, "equity.csv", EQUITY_COLS, rows)

    def append_ledger(self, name, rows):
        self._append(name, "ledger.csv", LEDGER_COLS, rows)

    def record_run(self, name, rec):
        with open(self.est_dir(name) / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def load_runs(self, name):
        p = self.est_dir(name) / "runs.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

    def _load(self, name, fname, cols):
        p = self.est_dir(name) / fname
        if not p.exists():
            return pd.DataFrame(columns=cols)
        df = pd.read_csv(p, dtype={"date": str, "settle_date": str, "asof": str})
        if list(df.columns) != cols:
            raise SchemaMismatch(f"{p} has columns {list(df.columns)}, expected {cols}")
        return df

    def _append(self, name, fname, cols, rows):
        if not rows:
            return
        new = pd.DataFrame(rows, columns=cols)
        old = self._load(name, fname, cols)
        out = new if old.empty else pd.concat([old, new], ignore_index=True)
        out.to_csv(self.est_dir(name) / fname, index=False, lineterminator="\n")
