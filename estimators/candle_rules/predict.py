from estimators.base import Estimator, Prediction

CALL = 0.002  # fixed size of the call; the rules say direction, not magnitude


def _signal(o, h, l, c):
    """+1 bullish, -1 bearish, 0 nothing. Arrays hold the last 5 candles, oldest first."""
    rng = h[-1] - l[-1]
    body = abs(c[-1] - o[-1])
    upper = h[-1] - max(o[-1], c[-1])
    lower = min(o[-1], c[-1]) - l[-1]
    down, up = c[-2] < c[-5], c[-2] > c[-5]
    if rng > 0 and body <= 0.3 * rng:
        if down and lower >= 2 * body and upper <= 0.1 * rng:
            return 1  # hammer after a decline
        if up and upper >= 2 * body and lower <= 0.1 * rng:
            return -1  # shooting star after a rise
    prev_red, prev_green = c[-2] < o[-2], c[-2] > o[-2]
    cur_green, cur_red = c[-1] > o[-1], c[-1] < o[-1]
    if prev_red and cur_green and o[-1] <= c[-2] and c[-1] >= o[-2]:
        return 1  # bullish engulfing
    if prev_green and cur_red and o[-1] >= c[-2] and c[-1] <= o[-2]:
        return -1  # bearish engulfing
    return 0


class CandleRules(Estimator):
    name = "candle_rules"

    def predict(self, history, assets):
        out = {}
        for a in assets:
            df = history[a]
            if len(df) < 5:
                continue
            tail = df.tail(5)
            o, h, l, c = (tail[x].to_numpy(float) for x in ("open", "high", "low", "close"))
            out[a] = Prediction(CALL * _signal(o, h, l, c))
        return out
