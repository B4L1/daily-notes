import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bench.config import load_config
from bench.data import load_prices, update_prices
from bench.runner import run_estimator_day
from bench.store import Store
from estimators import registry


def _data():
    return Path(os.environ.get("BENCH_DATA", "data"))


def _assets_file():
    return os.environ.get("BENCH_ASSETS", "assets.yaml")


def _site():
    return Path(os.environ.get("BENCH_SITE", "site"))


def _run_date(arg, now):
    return arg or now.date().isoformat()


def cmd_list(args, now):
    print(json.dumps(registry.names()))
    return 0


def cmd_requirements(args, now):
    print(registry.REGISTRY[args.estimator].get("requirements", ""))
    return 0


def cmd_setup(args, now):
    """Run an estimator's one-off preparation (weights, pinned sources), if it has one."""
    import importlib

    module = registry.REGISTRY[args.estimator].get("setup")
    if module:
        importlib.import_module(module).main()
    return 0


def cmd_fetch(args, now):
    settings, assets = load_config(_assets_file())
    status = update_prices(
        _data() / "prices", assets, settings.history_start,
        through=(date.fromisoformat(_run_date(None, now)) - timedelta(days=1)).isoformat(),
    )
    split = False
    for symbol, s in status.items():
        print(f"{symbol}: {s}")
        for line in revision_warnings(symbol, s):
            print(line)
        split = split or bool(getattr(s, "split_like", False))
    return 1 if split or all(s != "ok" for s in status.values()) else 0


def revision_warnings(symbol, s, max_examples=3):
    """WARNING lines for a refresh whose source disagrees with stored candles (kept as stored)."""
    revisions = getattr(s, "revisions", None)
    if not revisions:
        return []
    days = sorted({r["date"] for r in revisions})
    lines = [
        f"WARNING: {symbol}: the source revised {len(revisions)} stored value(s) on {len(days)} date(s) "
        f"({days[0]} to {days[-1]}); stored values were KEPT (the price cache is append-only)."
    ]
    for r in revisions[:max_examples]:
        lines.append(f"WARNING: {symbol} {r['date']} {r['field']}: old {r['old']:.6g}, new {r['new']:.6g}")
    if s.split_like:
        lines.append(
            f"WARNING: {symbol}: possible split: manual re-base needed (new/old ratio is constant at "
            f"{s.ratio:.4g} over {s.overlap_days} overlapping days). See docs/data-sources.md, "
            "'Corrections and splits'."
        )
    return lines


def cmd_run(args, now):
    settings, assets = load_config(_assets_file())
    prices = load_prices(_data() / "prices", assets)
    estimator = registry.build(args.estimator)
    rec = run_estimator_day(
        Store(_data() / "live"), estimator, prices, _run_date(args.run_date, now), settings, now=now
    )
    print(json.dumps(rec))
    return 0 if rec["status"] in ("ok", "skipped_late") else 1


def cmd_backfill(args, now):
    settings, assets = load_config(_assets_file())
    prices = load_prices(_data() / "prices", assets)
    estimator = registry.build(args.estimator)
    store = Store(_data() / "backtest")
    end = date.fromisoformat(args.end) if args.end else now.date()
    days = [(end - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)]
    stride = max(1, estimator.backfill_stride)
    failed = 0
    for i, d in enumerate(days):
        if i % stride and i != len(days) - 1:
            continue
        rec = run_estimator_day(store, estimator, prices, d, settings)
        failed += rec["status"] == "failed"
        if i % 25 == 0:
            print(f"backfill {args.estimator}: {d} ({rec['status']})", file=sys.stderr)
    print(json.dumps({"estimator": args.estimator, "days": len(days), "failed_days": failed}))
    return 0


def cmd_aggregate(args, now):
    from bench.aggregate import build_all

    settings, assets = load_config(_assets_file())
    prices = load_prices(_data() / "prices", assets)
    build_all(
        _data(), _site() / "data", prices, settings, assets, _run_date(args.run_date, now),
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return 0


def cmd_notify(args, now):
    from bench.notify import notify

    return notify(
        _site() / "data" / "summary.json", _run_date(args.run_date, now), args.failure, os.environ
    )


def main(argv=None, now=None):
    now = now or datetime.now(timezone.utc)
    p = argparse.ArgumentParser(prog="bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("fetch")
    r = sub.add_parser("requirements")
    r.add_argument("--estimator", required=True)
    r = sub.add_parser("setup")
    r.add_argument("--estimator", required=True)
    r = sub.add_parser("run")
    r.add_argument("--estimator", required=True)
    r.add_argument("--run-date")
    b = sub.add_parser("backfill")
    b.add_argument("--estimator", required=True)
    b.add_argument("--days", type=int, default=365)
    b.add_argument("--end")
    a = sub.add_parser("aggregate")
    a.add_argument("--run-date")
    n = sub.add_parser("notify")
    n.add_argument("--run-date")
    n.add_argument("--failure", action="store_true")
    args = p.parse_args(argv)
    commands = {
        "list": cmd_list, "requirements": cmd_requirements, "setup": cmd_setup, "fetch": cmd_fetch, "run": cmd_run,
        "backfill": cmd_backfill, "aggregate": cmd_aggregate, "notify": cmd_notify,
    }
    return commands[args.cmd](args, now)


if __name__ == "__main__":
    sys.exit(main())
