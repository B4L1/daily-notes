def net_return(entry, exit_, cost):
    return exit_ / entry - 1.0 - cost


def should_trade(expected_return, threshold):
    return expected_return > threshold


def _targets(prices):
    """(asset, asof) -> (target_date, open, close, previous_close) for every consecutive candle pair."""
    out = {}
    for asset, df in prices.items():
        d, o, c = df["date"].tolist(), df["open"].tolist(), df["close"].tolist()
        for i in range(1, len(d)):
            out[(asset, d[i - 1])] = (d[i], o[i], c[i], c[i - 1])
    return out


def _sessions_per_date(prices):
    counts = {}
    for df in prices.values():
        for d in df["date"]:
            counts[d] = counts.get(d, 0) + 1
    return counts


def settle_estimator(store, name, prices, settings):
    by_key = {}
    saved = store.load_predictions(name)  # read the prediction files once
    for run_date in sorted(saved):
        payload = saved[run_date]
        for asset, p in payload["predictions"].items():
            by_key[(asset, p["asof"])] = p

    targets = _targets(prices)
    days = {}
    for (asset, asof), p in by_key.items():
        if (asset, asof) in targets:
            t, o, c, prev_c = targets[(asset, asof)]
            days.setdefault(t, {})[asset] = (p, o, c, prev_c)

    equity = store.load_equity(name)
    last_done = equity["date"].iloc[-1] if len(equity) else ""
    eq = float(equity["equity"].iloc[-1]) if len(equity) else float(settings.start_equity)
    sessions = _sessions_per_date(prices)

    ledger_rows, equity_rows = [], []
    for t in sorted(days):
        if t <= last_done:
            continue
        total, n_traded = 0.0, 0
        for asset, (p, o, c, prev_c) in sorted(days[t].items()):
            exp = p["expected_return"]
            traded = should_trade(exp, settings.trade_threshold)
            gross = c / o - 1.0
            net = net_return(o, c, settings.cost_round_trip) if traded else 0.0
            actual_cc = c / prev_c - 1.0
            hit = None if (exp == 0 or actual_cc == 0) else int((exp > 0) == (actual_cc > 0))
            total += net
            n_traded += int(traded)
            ledger_rows.append({
                "settle_date": t, "asset": asset, "asof": p["asof"], "entry": o, "exit": c,
                "expected_return": exp, "traded": int(traded), "gross_ret": gross,
                "net_ret": net, "actual_cc": actual_cc, "hit": hit,
            })
        n_universe = sessions[t]
        day_return = total / n_universe
        eq *= 1.0 + day_return
        equity_rows.append({
            "date": t, "equity": eq, "day_return": day_return,
            "n_universe": n_universe, "n_traded": n_traded,
        })
        last_done = t

    store.append_ledger(name, ledger_rows)
    store.append_equity(name, equity_rows)
    return len(equity_rows)
