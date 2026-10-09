from bench.strategies.common import Result, by_target, finish, hit_flag, row


def _run(preds, prices, costs, start_equity, short=False, top_n=None):
    rows = []
    days = by_target(preds, prices)
    for t in sorted(days):
        day = days[t]
        longs = {a for a, (p, *_x) in day.items() if p["expected_return"] > costs.round_trip(a)}
        if top_n is not None:
            ranked = sorted(longs, key=lambda a: (-day[a][0]["expected_return"], -(day[a][0].get("confidence") or 0.0), a))
            longs = set(ranked[:top_n])
        for asset in sorted(day):
            p, o, c, prev_c = day[asset]
            exp = p["expected_return"]
            rt = costs.round_trip(asset)
            gross = c / o - 1.0
            actual_cc = c / prev_c - 1.0
            if asset in longs:
                side, traded, net, cost = "long", 1, gross - rt, rt
            elif short and exp < -rt:
                cost = rt + costs.borrow_day(asset)
                side, traded, net = "short", 1, -gross - cost
            else:
                side, traded, net, cost = "none", 0, 0.0, 0.0
            rows.append(row(t, asset, costs, p["asof"], side, "day", o, c, exp, traded, net, cost,
                            actual_cc, hit_flag(exp, actual_cc)))
    return Result(rows, finish(rows, prices, start_equity), [])


def one_day(preds, prices, costs, start_equity):
    """Buy at the open, sell at the close, when the expected gain beats the asset's cost."""
    return _run(preds, prices, costs, start_equity)


TOP_N = 3


def one_day_short(preds, prices, costs, start_equity):
    """As one_day, and also short at the open when the expected fall beats the asset's cost."""
    return _run(preds, prices, costs, start_equity, short=True)


def top_picks(preds, prices, costs, start_equity):
    """As one_day, but only the day's three strongest calls."""
    return _run(preds, prices, costs, start_equity, top_n=TOP_N)
