class Costs:
    """What it costs to trade each asset. All values are fractions of the position."""

    def __init__(self, assets):
        self._assets = {a.symbol: a for a in assets}

    def round_trip(self, symbol):
        return float(self._assets[symbol].cost_round_trip)

    def half(self, symbol):
        return self.round_trip(symbol) / 2.0

    def borrow_day(self, symbol):
        return float(self._assets[symbol].borrow_annual) / 360.0

    def group(self, symbol):
        return self._assets[symbol].group
