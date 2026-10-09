from bench.strategies.common import Result, by_target, finish, hit_flag, row, sessions


def _candles(prices):
    """asset -> {date: (open, close, previous close or None)}."""
    out = {}
    for asset, df in prices.items():
        d, o, c = df["date"].tolist(), df["open"].tolist(), df["close"].tolist()
        out[asset] = {d[i]: (float(o[i]), float(c[i]), float(c[i - 1]) if i else None) for i in range(len(d))}
    return out


def hold(preds, prices, costs, start_equity):
    """Buy when the expected gain beats the round-trip cost; sell at the next open once the
    model stops expecting a gain. Costs are paid only on entry and on exit."""
    days = by_target(preds, prices)
    if not days:
        return Result([], [], [])
    first = min(days)
    sess = sessions(prices)
    cand = _candles(prices)
    held, rows, open_after, last_seen = {}, [], {}, {}
    for d in sorted(x for x in sess if x >= first):
        for asset in sess[d]:
            o, c, prev_c = cand[asset][d]
            if prev_c is None:
                continue
            entry = days.get(d, {}).get(asset)
            p = entry[0] if entry else None
            exp = p["expected_return"] if p else None
            asof = p["asof"] if p else None
            actual_cc = c / prev_c - 1.0
            hit = hit_flag(exp, actual_cc) if p else None
            half = costs.half(asset)
            if asset in held:
                if p and exp > 0:
                    rows.append(row(d, asset, costs, asof, "long", "hold", prev_c, c, exp, 1,
                                    actual_cc, 0.0, actual_cc, hit))
                    last_seen[asset] = (d, c)
                else:
                    rows.append(row(d, asset, costs, asof, "long", "close", prev_c, o, exp, 1,
                                    o / prev_c - 1.0 - half, half, actual_cc, hit))
                    del held[asset]
            elif p and exp > costs.round_trip(asset):
                rows.append(row(d, asset, costs, asof, "long", "open", o, c, exp, 1,
                                c / o - 1.0 - half, half, actual_cc, hit))
                held[asset] = (d, o)
                last_seen[asset] = (d, c)
            elif p:
                rows.append(row(d, asset, costs, asof, "none", "none", o, c, exp, 0, 0.0, 0.0, actual_cc, hit))
        open_after[d] = len(held)
    positions = [
        {
            "asset": a, "group": costs.group(a), "side": "long", "entry_date": held[a][0], "entry": held[a][1],
            "last_date": last_seen[a][0], "last": last_seen[a][1],
            "unrealised": last_seen[a][1] / held[a][1] - 1.0 - costs.half(a),
        }
        for a in sorted(held)
    ]
    return Result(rows, finish(rows, prices, start_equity, open_after, universe="listed"), positions)
