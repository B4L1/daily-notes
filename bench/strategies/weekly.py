import math

from bench.strategies.common import Result, finish, hit_flag, row

HORIZON = 5
WEIGHT = 1.0 / HORIZON


def _usable(p):
    path = p.get("path")
    if not path or len(path) < HORIZON:
        return False
    try:
        return math.isfinite(float(path[HORIZON - 1]))
    except (TypeError, ValueError):
        return False


def weekly(preds, prices, costs, start_equity):
    """Five overlapping 5-session slots per asset, each a fifth of the asset's share.

    Returns None for a model whose predictions carry no 5-day path.
    """
    usable = {k: p for k, p in preds.items() if _usable(p)}
    if not usable:
        return None
    rows, positions, spans = [], [], []  # spans: (entry date, close date or None) of traded slots
    for asset in sorted(prices):
        df = prices[asset]
        d, o, c = df["date"].tolist(), [float(x) for x in df["open"]], [float(x) for x in df["close"]]
        rt, half = costs.round_trip(asset), costs.half(asset)
        slots = []  # (start index, expected 5-day return, traded, asof)
        for i in range(1, len(d)):
            p = usable.get((asset, d[i - 1]))
            if p is not None:
                exp5 = float(p["path"][HORIZON - 1]) / c[i - 1] - 1.0
                slots.append((i, exp5, exp5 > rt, p["asof"]))
                if exp5 > rt:
                    spans.append((d[i], d[i + HORIZON - 1] if i + HORIZON - 1 < len(d) else None))
            actual_cc = c[i] / c[i - 1] - 1.0
            for start, exp5, traded, asof in slots:
                age = i - start
                if age < 0 or age >= HORIZON:
                    continue
                last = age == HORIZON - 1
                hit5 = hit_flag(exp5, c[i] / c[start - 1] - 1.0) if last else None
                if not traded:
                    if age == 0:
                        rows.append(row(d[i], asset, costs, asof, "none", "none", o[i], c[i], exp5, 0, 0.0, 0.0,
                                        actual_cc, None, None, WEIGHT))
                    elif last:
                        rows.append(row(d[i], asset, costs, asof, "none", "mark", o[i], c[i], exp5, 0, 0.0, 0.0,
                                        actual_cc, None, hit5, WEIGHT))
                    continue
                if age == 0:
                    rows.append(row(d[i], asset, costs, asof, "long", "open", o[i], c[i], exp5, 1,
                                    c[i] / o[i] - 1.0 - half, half, actual_cc, None, None, WEIGHT))
                elif last:
                    rows.append(row(d[i], asset, costs, asof, "long", "close", c[i - 1], c[i], exp5, 1,
                                    actual_cc - half, half, actual_cc, None, hit5, WEIGHT))
                else:
                    rows.append(row(d[i], asset, costs, asof, "long", "hold", c[i - 1], c[i], exp5, 1,
                                    actual_cc, 0.0, actual_cc, None, None, WEIGHT))
            slots = [s for s in slots if i - s[0] < HORIZON - 1]  # a slot's last session is done
        n = len(d) - 1
        for start, exp5, traded, asof in slots:
            if traded and n - start < HORIZON - 1:
                positions.append({
                    "asset": asset, "group": costs.group(asset), "side": "long", "entry_date": d[start],
                    "entry": o[start], "last_date": d[n], "last": c[n],
                    "unrealised": c[n] / o[start] - 1.0 - half,
                })
    delta = {}
    for entry, close in spans:
        delta[entry] = delta.get(entry, 0) + 1
        if close is not None:
            delta[close] = delta.get(close, 0) - 1
    open_after, running = {}, 0
    for dt in sorted({x for df in prices.values() for x in df["date"].tolist()}):
        running += delta.get(dt, 0)
        open_after[dt] = running
    rows.sort(key=lambda r: (r["date"], r["asset"], r["asof"]))
    return Result(rows, finish(rows, prices, start_equity, open_after), positions)
