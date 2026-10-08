from bench.strategies import daily, hold, weekly

STRATEGIES = {
    "one_day": daily.one_day,
    "one_day_short": daily.one_day_short,
    "hold": hold.hold,
    "top_picks": daily.top_picks,
    "weekly": weekly.weekly,
}
