import json
import os
from pathlib import Path

import pandas as pd

from bench.strategies.common import EQUITY_COLS as ACCT_EQUITY_COLS, LEDGER_COLS as ACCT_LEDGER_COLS

SCHEMA_VERSION = 2


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
        (d / f"{run_date}.json").write_text(text, encoding="utf-8", newline="")

    def load_predictions(self, name):
        d = self.est_dir(name) / "predictions"
        out = {}
        for f in sorted(d.glob("*.json")):
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        return out

    def record_run(self, name, rec):
        with open(self.est_dir(name) / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def load_runs(self, name):
        p = self.est_dir(name) / "runs.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

    def acct_dir(self, model, strategy):
        return self.root / "accounts" / model / strategy

    @staticmethod
    def render_account(result):
        """An account Result as its three file texts. Empty for an empty ledger. Raises on non-finite values."""
        if not result.ledger:
            return {}
        return {
            "ledger.csv": pd.DataFrame(result.ledger, columns=ACCT_LEDGER_COLS).to_csv(index=False, lineterminator="\n"),
            "equity.csv": pd.DataFrame(result.equity, columns=ACCT_EQUITY_COLS).to_csv(index=False, lineterminator="\n"),
            "positions.json": json.dumps(result.positions, indent=1, sort_keys=True, allow_nan=False) + "\n",
        }

    def write_account(self, model, strategy, texts):
        """Overwrite one account's files with texts from render_account. No texts removes them."""
        d = self.acct_dir(model, strategy)
        if not texts:
            for n in ("ledger.csv", "equity.csv", "positions.json"):
                (d / n).unlink(missing_ok=True)
            for p in (d, d.parent):
                if p.exists() and not any(p.iterdir()):
                    p.rmdir()
            return
        d.mkdir(parents=True, exist_ok=True)
        for n, text in texts.items():
            tmp = d / f".{n}.tmp"
            tmp.write_text(text, encoding="utf-8", newline="")
            os.replace(tmp, d / n)

    def load_account(self, model, strategy):
        d = self.acct_dir(model, strategy)
        out = []
        for fname, cols in (("equity.csv", ACCT_EQUITY_COLS), ("ledger.csv", ACCT_LEDGER_COLS)):
            p = d / fname
            if not p.exists():
                out.append(pd.DataFrame(columns=cols))
                continue
            df = pd.read_csv(p, dtype={"date": str, "asof": str, "asset": str})
            if list(df.columns) != cols:
                raise SchemaMismatch(f"{p} has columns {list(df.columns)}, expected {cols}")
            out.append(df)
        return out[0], out[1]

    def load_positions(self, model, strategy):
        p = self.acct_dir(model, strategy) / "positions.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def replace_predictions(self, model, by_run_date):
        """Overwrite a derived model's whole prediction set."""
        d = self.root / "estimators" / model / "predictions"
        if d.exists():
            for f in d.glob("*.json"):
                if f.stem not in by_run_date:
                    f.unlink()
        for run_date, payload in by_run_date.items():
            self.save_prediction(model, run_date, payload)
