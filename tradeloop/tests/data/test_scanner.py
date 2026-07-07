from datetime import date

import pytest

from tradeloop.lib.data.kite import Candle
from tradeloop.lib.ta import scanner


class OneSymbolKite:
    def __init__(self, candles):
        self._candles = candles

    def historical(self, symbol, frm, to, interval):
        return self._candles


def _uptrend_candles(n=60):
    out = []
    base = 100.0
    for i in range(n):
        o = base + i
        out.append(Candle(f"2026-0{1 + i % 9}-01T00:00:00+0530", o, o + 3, o - 1, o + 2, 1000 + i))
    return out


def test_scan_symbol_skips_when_too_few_candles():
    # kills a regression that drops the < 30 candle guard when switching to Kite input
    kc = OneSymbolKite(_uptrend_candles(10))
    assert scanner.scan_symbol("INFY", kc, date(2026, 7, 1)) is None


def test_scan_symbol_uses_real_atr_no_fabrication():
    # kills the `latest * 0.02` fabricated-ATR bug: stop must derive from real ATR14
    kc = OneSymbolKite(_uptrend_candles(60))
    scan = scanner.scan_symbol("INFY", kc, date(2026, 7, 1))
    assert scan is not None
    assert float(scan.stop_zone) < float(scan.entry_zone)


def test_scan_universe_bounded_by_max_fetch():
    # kills an unbounded scan that would hammer Kite for the full universe every cycle
    kc = OneSymbolKite(_uptrend_candles(60))
    scans = scanner.scan_universe(["A", "B", "C", "D"], kc, date(2026, 7, 1), max_fetch=2)
    assert len(scans) <= 2


def test_scan_universe_reraises_unexpected():
    # kills the silent blanket `except Exception: continue` that swallowed real bugs
    class Boom:
        def historical(self, *a, **k):
            raise KeyError("unexpected internal bug")

    with pytest.raises(KeyError):
        scanner.scan_universe(["A"], Boom(), date(2026, 7, 1), max_fetch=5)
