from typing import NamedTuple

LEDGER_COLS = [
    "date", "asset", "group", "asof", "side", "action", "entry", "exit", "expected_return",
    "traded", "net_ret", "weight", "cost", "actual_cc", "hit", "hit5",
]
EQUITY_COLS = ["date", "equity", "day_return", "n_universe", "n_traded", "n_open"]
FEE_ACTIONS = ("day", "open", "close")


class Result(NamedTuple):
    ledger: list
    equity: list
    positions: list


def index_predictions(saved):
    """{run_date: payload} -> {(asset, asof): prediction}. A later run date wins, as in V1."""
    out = {}
    for run_date in sorted(saved):
        for asset, p in saved[run_date]["predictions"].items():
            out[(asset, p["asof"])] = p
    return out


def targets(prices):
    """(asset, asof) -> (target date, open, close, previous close) for every consecutive candle pair."""
    out = {}
    for asset, df in prices.items():
        d, o, c = df["date"].tolist(), df["open"].tolist(), df["close"].tolist()
        for i in range(1, len(d)):
            out[(asset, d[i - 1])] = (d[i], float(o[i]), float(c[i]), float(c[i - 1]))
    return out


def sessions(prices):
    """date -> sorted assets that have a candle that day."""
    out = {}
    for asset, df in prices.items():
        for d in df["date"]:
            out.setdefault(d, []).append(asset)
    return {d: sorted(v) for d, v in out.items()}


def by_target(preds, prices):
    """target date -> {asset: (prediction, open, close, previous close)}."""
    tg = targets(prices)
    out = {}
    for (asset, asof), p in preds.items():
        if (asset, asof) in tg:
            t, o, c, prev_c = tg[(asset, asof)]
            out.setdefault(t, {})[asset] = (p, o, c, prev_c)
    return out


def hit_flag(expected, actual):
    """1 if the predicted direction was right, 0 if wrong, None when either side is flat."""
    if expected == 0 or actual == 0:
        return None
    return int((expected > 0) == (actual > 0))


def row(date, asset, costs, asof, side, action, entry, exit_, expected, traded, net, cost,
        actual_cc, hit, hit5=None, weight=1.0):
    return {
        "date": date, "asset": asset, "group": costs.group(asset), "asof": asof, "side": side,
        "action": action, "entry": entry, "exit": exit_, "expected_return": expected,
        "traded": int(traded), "net_ret": net, "weight": weight, "cost": cost,
        "actual_cc": actual_cc, "hit": hit, "hit5": hit5,
    }


def finish(rows, prices, start_equity, open_after=None, universe="session"):
    """Ledger rows -> equity rows. One row per date that has a ledger row.

    universe="session": a day's return is spread over the assets with a candle that day (accounts
    that hold nothing overnight). universe="listed": over every asset whose first candle is on or
    before that day, so a position kept over a day when its asset has no candle (a stock over a
    weekend) never makes the others count for more than their fixed share.
    """
    sess = sessions(prices)
    firsts = sorted(df["date"].iloc[0] for df in prices.values() if len(df))
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    eq, out = float(start_equity), []
    for d in sorted(by_date):
        n = len(sess[d]) if universe == "session" else sum(1 for f in firsts if f <= d)
        total = sum(r["net_ret"] * r["weight"] for r in by_date[d])
        day = max(total / n, -1.0)
        eq *= 1.0 + day
        out.append({
            "date": d, "equity": eq, "day_return": day, "n_universe": n,
            "n_traded": sum(r["traded"] for r in by_date[d] if r["action"] in FEE_ACTIONS),
            "n_open": (open_after or {}).get(d, 0),
        })
    return out
