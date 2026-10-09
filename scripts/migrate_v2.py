"""One-off: store schema 1 -> 2. V1 kept one ledger per estimator; V2 keeps accounts per strategy.

Predictions and run logs are untouched. Run `python -m bench.cli score` afterwards to rebuild accounts.
"""
import sys
from pathlib import Path


def migrate(data_dir="data"):
    done = []
    for mode in ("live", "backtest"):
        root = Path(data_dir) / mode
        marker = root / "SCHEMA"
        if not marker.exists():
            continue
        found = int(marker.read_text().strip())
        if found == 2:
            continue
        if found != 1:
            raise RuntimeError(f"{root} has schema {found}; this script only migrates 1 to 2")
        for name in ("equity.csv", "ledger.csv"):
            for f in sorted((root / "estimators").glob(f"*/{name}")) if (root / "estimators").exists() else []:
                f.unlink()
                done.append(f"removed {f.as_posix()}")
        marker.write_text("2\n")
        done.append(f"{marker.as_posix()}: 1 -> 2")
    return done


if __name__ == "__main__":
    for line in migrate(sys.argv[1] if len(sys.argv) > 1 else "data"):
        print(line)
