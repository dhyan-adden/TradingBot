from datetime import date

from tradeloop.lib.ta.scanner import scan_symbol, scan_universe
from tradeloop.lib.data.kite import Candle


def _candles(close, volume, n=60):
    # a clean rising series so a setup would normally register
    out = []
    for i in range(n):
        c = close + i * 0.5
        out.append(Candle(date=f"2026-01-{(i % 28) + 1:02d}", open=c, high=c + 1,
                          low=c - 1, close=c, volume=volume))
    return out


class FakeKite:
    def __init__(self, by_symbol):
        self.by_symbol = by_symbol
        self.seen = []

    def historical(self, symbol, frm, to, interval):
        self.seen.append(symbol)
        return self.by_symbol.get(symbol, [])


def test_liquidity_floor_drops_thin_symbol():
    # turnover = close(~50) * volume(100) ~= 5,000 << 1,000,000 floor -> dropped
    kite = FakeKite({"THIN": _candles(50.0, 100)})
    assert scan_symbol("THIN", kite, date(2026, 2, 2), min_turnover_inr=1_000_000) is None


def test_liquidity_floor_keeps_liquid_symbol():
    # turnover = close(~50) * volume(1,000,000) ~= 50M >> floor -> setup allowed
    kite = FakeKite({"LIQ": _candles(50.0, 1_000_000)})
    scan = scan_symbol("LIQ", kite, date(2026, 2, 2), min_turnover_inr=1_000_000)
    assert scan is not None and scan.ticker == "LIQ"


def test_scan_universe_paces_each_symbol():
    kite = FakeKite({"A": _candles(50.0, 1_000_000), "B": _candles(50.0, 1_000_000)})
    naps = []
    scan_universe(["A", "B"], kite, date(2026, 2, 2),
                  pace_seconds=0.34, sleep=lambda s: naps.append(s))
    assert naps == [0.34, 0.34]  # one nap per symbol
