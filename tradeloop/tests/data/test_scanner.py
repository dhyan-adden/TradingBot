from datetime import date

import pytest

from tradeloop.lib.data.kite import Candle, KiteAuthError
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
    # scan_symbol returns [] when fewer than 30 candles are available
    kc = OneSymbolKite(_uptrend_candles(10))
    assert scanner.scan_symbol("INFY", kc, date(2026, 7, 1)) == []


def test_scan_symbol_uses_real_atr_no_fabrication():
    # kills the `latest * 0.02` fabricated-ATR bug: stop must derive from real ATR14
    kc = OneSymbolKite(_uptrend_candles(60))
    scans = scanner.scan_symbol("INFY", kc, date(2026, 7, 1))
    assert scans, "expected at least one setup"
    scan = scans[0]
    assert float(scan.stop_zone) < float(scan.entry_zone)


def test_scan_symbol_returns_list():
    kc = OneSymbolKite(_uptrend_candles(60))
    result = scanner.scan_symbol("INFY", kc, date(2026, 7, 1))
    assert isinstance(result, list)


def test_scan_symbol_strategy_family_populated():
    kc = OneSymbolKite(_uptrend_candles(60))
    scans = scanner.scan_symbol("INFY", kc, date(2026, 7, 1))
    for s in scans:
        assert s.strategy_family, f"strategy_family is empty on {s.setup_type}"
        assert s.exit_rule, f"exit_rule is empty on {s.setup_type}"


def test_scan_targets_are_2r_and_3r_of_stop_distance():
    # 2026-07-13 debt: T1 at +2.0 ATR over a 1.5 ATR stop was a 1.33R first target -
    # structurally unable to clear the 0.3R promotion-gate expectancy after costs.
    # Targets are now R multiples of the actual stop distance: T1 = 2R, T2 = 3R.
    kc = OneSymbolKite(_uptrend_candles(60))
    scans = scanner.scan_symbol("INFY", kc, date(2026, 7, 1))
    assert scans
    scan = scans[0]
    entry, stop = float(scan.entry_zone), float(scan.stop_zone)
    t1, t2 = (float(x) for x in scan.target_zone.split("/"))
    risk = entry - stop
    assert abs((t1 - entry) - 2 * risk) < 0.03   # 2dp string rounding tolerance
    assert abs((t2 - entry) - 3 * risk) < 0.03


def test_scan_universe_bounded_by_max_fetch():
    # kills an unbounded scan that would hammer Kite for the full universe every cycle
    kc = OneSymbolKite(_uptrend_candles(60))
    scans = scanner.scan_universe(["A", "B", "C", "D"], kc, date(2026, 7, 1), max_fetch=2)
    # After deduplication 2 symbols → at most 2 distinct tickers
    assert len({s.ticker for s in scans}) <= 2


def test_scan_universe_reraises_unexpected():
    # kills the silent blanket `except Exception: continue` that swallowed real bugs
    class Boom:
        def historical(self, *a, **k):
            raise KeyError("unexpected internal bug")

    with pytest.raises(KeyError):
        scanner.scan_universe(["A"], Boom(), date(2026, 7, 1), max_fetch=5)


def test_scan_universe_reraises_auth_failure_without_per_symbol_skip():
    class AuthBoom:
        def historical(self, *a, **k):
            raise KiteAuthError("Zerodha authentication failed")

    with pytest.raises(KiteAuthError, match="Zerodha authentication failed"):
        scanner.scan_universe(["A", "B"], AuthBoom(), date(2026, 7, 1), max_fetch=5)
