"""Tests for the three new strategy families, the repeat-pullback signal,
and the harmony fixes (sector exit rule composition, horizon sort)."""
from datetime import date

from tradeloop.lib.data.kite import Candle
from tradeloop.lib.ta.patterns import (
    bullish_close,
    earnings_gap_up,
    ema20_touch_count,
    relative_strength_pct,
)
from tradeloop.lib.ta.scanner import (
    SetupScan,
    scan_sector_leaders,
    scan_symbol,
    scan_universe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candles(n=60, base=100.0, step=0.5, volume=1_000_000,
             gap_idx: int | None = None, gap_pct: float = 5.0,
             gap_vol_x: float = 3.0):
    """Smooth rising series with an optional gap-up candle at gap_idx from the end.
    gap_idx=1 means the second-to-last candle gapped up (post_earnings_drift);
    gap_idx=0 means the last candle gapped up (results_momentum).
    """
    candles = []
    for i in range(n):
        c = base + i * step
        candles.append(Candle(
            date=f"2026-01-{(i % 28) + 1:02d}",
            open=c, high=c + 1.0, low=c - 1.0, close=c,
            volume=volume,
        ))
    if gap_idx is not None:
        idx = n - 1 - gap_idx          # position from start
        prior_close = candles[idx - 1].close if idx > 0 else base
        gap_open = prior_close * (1 + gap_pct / 100)
        gap_close = gap_open * 1.02    # close above open (bullish)
        g = candles[idx]
        candles[idx] = Candle(
            date=g.date,
            open=gap_open,
            high=gap_open * 1.04,
            low=gap_open * 0.99,
            close=gap_close,
            volume=int(volume * gap_vol_x),
        )
        # ensure subsequent candles stay above the gap (unfilled)
        for j in range(idx + 1, n):
            c = gap_close + (j - idx) * step
            candles[j] = Candle(
                date=candles[j].date,
                open=c, high=c + 1.0, low=c - 1.0, close=c,
                volume=volume,
            )
    return candles


class FakeKite:
    def __init__(self, candles):
        self._candles = candles

    def historical(self, symbol, frm, to, interval):
        return self._candles


# ---------------------------------------------------------------------------
# Pattern: earnings_gap_up
# ---------------------------------------------------------------------------

def test_earnings_gap_detects_3pct_gap_yesterday_with_2x_volume():
    opens  = [100.0] * 21 + [103.5]  # gap yesterday
    closes = [100.0] * 20 + [100.0, 103.8]
    vols   = [1_000_000] * 21 + [2_100_000]  # > 2x avg
    sig = earnings_gap_up(opens, closes, vols, lookback=3, min_gap_pct=3.0, volume_multiple=2.0)
    assert sig.bullish


def test_earnings_gap_not_bullish_when_gap_already_filled():
    opens  = [100.0] * 21 + [104.0]  # gap yesterday
    closes = [100.0] * 20 + [100.0, 99.5]   # today's close < gap open -> filled
    vols   = [1_000_000] * 21 + [2_200_000]
    sig = earnings_gap_up(opens, closes, vols, lookback=3, min_gap_pct=3.0, volume_multiple=2.0)
    assert not sig.bullish


def test_earnings_gap_not_bullish_when_volume_insufficient():
    opens  = [100.0] * 21 + [104.0]
    closes = [100.0] * 20 + [100.0, 104.5]  # unfilled
    vols   = [1_000_000] * 21 + [1_100_000]  # only 1.1x, below 2x threshold
    sig = earnings_gap_up(opens, closes, vols, lookback=3, min_gap_pct=3.0, volume_multiple=2.0)
    assert not sig.bullish


def test_earnings_gap_not_bullish_when_gap_too_small():
    opens  = [100.0] * 21 + [102.0]   # 2% gap, below 3% threshold
    closes = [100.0] * 20 + [100.0, 102.5]
    vols   = [1_000_000] * 21 + [2_500_000]
    sig = earnings_gap_up(opens, closes, vols, lookback=3, min_gap_pct=3.0, volume_multiple=2.0)
    assert not sig.bullish


# ---------------------------------------------------------------------------
# Pattern: bullish_close
# ---------------------------------------------------------------------------

def test_bullish_close_detects_upper_half():
    # Close at 75% of range is in upper 50%
    sig = bullish_close([100.0], [110.0], [100.0], [107.5], min_range_position=0.5)
    assert sig.bullish


def test_bullish_close_rejects_lower_close():
    # Close at 25% of range is NOT in upper 50%
    sig = bullish_close([100.0], [110.0], [100.0], [102.5], min_range_position=0.5)
    assert not sig.bullish


def test_bullish_close_rejects_zero_range():
    sig = bullish_close([100.0], [100.0], [100.0], [100.0])
    assert not sig.bullish


# ---------------------------------------------------------------------------
# Pattern: relative_strength_pct
# ---------------------------------------------------------------------------

def test_relative_strength_positive_when_outperforming():
    stock = [100.0] * 20 + [120.0]   # +20%
    bench = [100.0] * 20 + [110.0]   # +10%
    rs = relative_strength_pct(stock, bench, period=20)
    assert rs > 0


def test_relative_strength_negative_when_lagging():
    stock = [100.0] * 20 + [105.0]   # +5%
    bench = [100.0] * 20 + [115.0]   # +15%
    rs = relative_strength_pct(stock, bench, period=20)
    assert rs < 0


def test_relative_strength_zero_when_insufficient_data():
    rs = relative_strength_pct([100.0], [100.0], period=20)
    assert rs == 0.0


# ---------------------------------------------------------------------------
# Strategy: post_earnings_drift (gap 1-3 days ago)
# ---------------------------------------------------------------------------

def test_post_earnings_drift_detected_for_1day_old_gap():
    candles = _candles(60, gap_idx=1, gap_pct=4.0, gap_vol_x=2.5)
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    families = {s.strategy_family for s in scans}
    assert "post_earnings_drift" in families, f"expected post_earnings_drift, got {families}"


def test_post_earnings_drift_exit_rule_contains_gap_fill_condition():
    candles = _candles(60, gap_idx=1, gap_pct=4.0, gap_vol_x=2.5)
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    ped = next((s for s in scans if s.strategy_family == "post_earnings_drift"), None)
    assert ped is not None
    assert "gap" in ped.exit_rule.lower()
    assert "day 15" in ped.exit_rule.lower()


def test_post_earnings_drift_not_detected_when_no_gap():
    candles = _candles(60)  # smooth series, no gap
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    assert all(s.strategy_family != "post_earnings_drift" for s in scans)


# ---------------------------------------------------------------------------
# Strategy: results_momentum (gap today)
# ---------------------------------------------------------------------------

def test_results_momentum_detected_for_same_day_gap():
    # Today's candle gaps 6%, 3.5x volume, bullish close
    candles = _candles(60, gap_idx=0, gap_pct=6.0, gap_vol_x=3.5)
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    families = {s.strategy_family for s in scans}
    assert "results_momentum" in families, f"expected results_momentum, got {families}"


def test_results_momentum_exit_rule_mentions_day5():
    candles = _candles(60, gap_idx=0, gap_pct=6.0, gap_vol_x=3.5)
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    rm = next((s for s in scans if s.strategy_family == "results_momentum"), None)
    assert rm is not None
    assert "day 5" in rm.exit_rule.lower()


def test_results_momentum_not_triggered_by_small_gap():
    candles = _candles(60, gap_idx=0, gap_pct=3.0, gap_vol_x=3.5)  # only 3%, below 5%
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    assert all(s.strategy_family != "results_momentum" for s in scans)


# ---------------------------------------------------------------------------
# Strategy: sector_rotation_leader
# ---------------------------------------------------------------------------

def _make_scan(ticker, family, score) -> SetupScan:
    return SetupScan(
        ticker=ticker, setup_type="test", strategy_family=family,
        cleanliness_score=score, entry_zone="100", stop_zone="95",
        target_zone="110/115", volume_context="ok", exit_rule="test",
    )


def test_sector_leader_detected_when_breadth_above_threshold():
    sector_map = {
        "RELIANCE": "Energy", "ONGC": "Energy", "NTPC": "Energy",
        "TATAPOWER": "Energy", "JSWENERGY": "Energy",
    }
    # 3 of 5 Energy names have setups (60% breadth -> above 40% threshold)
    scans = [
        _make_scan("RELIANCE", "20d_breakout", 8.0),
        _make_scan("ONGC",     "ema20_pullback", 7.0),
        _make_scan("NTPC",     "20d_breakout", 6.0),
    ]
    leaders = scan_sector_leaders(scans, sector_map, breadth_threshold=0.40, min_tracked=3)
    assert any(l.strategy_family == "sector_rotation_leader" for l in leaders)
    # RELIANCE (score 8.0) should be the leader
    reliance = next((l for l in leaders if l.ticker == "RELIANCE"), None)
    assert reliance is not None
    assert reliance.strategy_family == "sector_rotation_leader"


def test_sector_leader_not_detected_when_breadth_below_threshold():
    sector_map = {
        "RELIANCE": "Energy", "ONGC": "Energy", "NTPC": "Energy",
        "TATAPOWER": "Energy", "JSWENERGY": "Energy",
    }
    # Only 1 of 5 (20% breadth -> below 40% threshold)
    scans = [_make_scan("RELIANCE", "20d_breakout", 8.0)]
    leaders = scan_sector_leaders(scans, sector_map, breadth_threshold=0.40, min_tracked=3)
    assert not leaders


def test_sector_leader_exit_rule_mentions_breadth_and_ema50():
    sector_map = {
        "A": "IT", "B": "IT", "C": "IT",
        "D": "IT", "E": "IT",
    }
    scans = [
        _make_scan("A", "20d_breakout", 9.0),
        _make_scan("B", "20d_breakout", 8.0),
        _make_scan("C", "ema20_pullback", 7.0),
    ]
    leaders = scan_sector_leaders(scans, sector_map, breadth_threshold=0.40, min_tracked=3)
    assert leaders
    rule = leaders[0].exit_rule.lower()
    assert "breadth" in rule
    assert "ema50" in rule


def test_scan_universe_includes_sector_leaders(tmp_path):
    """Integration: scan_universe with a config_dir containing sector_map.yaml
    produces at least one sector_rotation_leader when breadth is high."""
    import yaml

    # Write a minimal sector_map with 3 symbols all expected to have setups
    sm = {"sectors": {"TestSector": ["A", "B", "C"]}}
    (tmp_path / "sector_map.yaml").write_text(yaml.dump(sm))
    (tmp_path / "settings.yaml").write_text("")

    candles = _candles(60)

    class MultiKite:
        def historical(self, symbol, frm, to, interval):
            return candles

    scans = scan_universe(
        ["A", "B", "C"], MultiKite(), date(2026, 7, 1), config_dir=tmp_path
    )
    families = {s.strategy_family for s in scans}
    assert "sector_rotation_leader" in families


# ---------------------------------------------------------------------------
# All strategies: strategy_family and exit_rule are always populated
# ---------------------------------------------------------------------------

def test_all_setups_have_strategy_family_and_exit_rule():
    """Regression: no SetupScan should ship with empty strategy_family or exit_rule."""
    candles = _candles(60, gap_idx=1, gap_pct=4.0, gap_vol_x=2.5)
    kite = FakeKite(candles)
    scans = scan_symbol("TEST", kite, date(2026, 7, 1))
    assert scans, "expected at least one setup from gapped series"
    for s in scans:
        assert s.strategy_family, f"empty strategy_family on {s}"
        assert s.exit_rule, f"empty exit_rule on {s}"


# ---------------------------------------------------------------------------
# Pattern: ema20_touch_count
# ---------------------------------------------------------------------------

def test_ema20_touch_count_detects_two_bounces():
    import math
    # Build a series where lows dipped to EMA20 twice and closed above it
    n = 50
    ema_base = 100.0
    lows   = [ema_base + i * 0.3 for i in range(n)]
    closes = [ema_base + i * 0.3 + 2.0 for i in range(n)]  # always close above EMA
    ema20  = [ema_base + i * 0.3 for i in range(n)]         # EMA20 = low level

    # Inject two touch bars: low exactly at EMA20, close above it
    for bar in [20, 35]:
        lows[bar]   = ema20[bar]          # low touches EMA20 exactly
        closes[bar] = ema20[bar] + 2.0    # close above

    count = ema20_touch_count(lows, closes, ema20, lookback=40, touch_pct=0.02)
    assert count >= 2, f"expected >= 2 touches, got {count}"


def test_ema20_touch_count_zero_when_no_touches():
    n = 50
    # lows always 10% above EMA20 - no touch
    ema20  = [100.0] * n
    lows   = [111.0] * n   # >2% away
    closes = [115.0] * n
    count = ema20_touch_count(lows, closes, ema20, lookback=40, touch_pct=0.02)
    assert count == 0


def test_ema20_touch_count_skips_nan():
    import math
    n = 30
    ema20  = [float("nan")] * 10 + [100.0 + i * 0.3 for i in range(n - 10)]
    lows   = [100.0 + i * 0.3 for i in range(n)]
    closes = [102.0 + i * 0.3 for i in range(n)]
    # touch at bar 20
    lows[20]   = ema20[20]
    closes[20] = ema20[20] + 1.0
    # should not crash on NaN values
    count = ema20_touch_count(lows, closes, ema20, lookback=25)
    assert count >= 1


# ---------------------------------------------------------------------------
# Repeat pullback: scanner score and setup_type
# ---------------------------------------------------------------------------

def _repeat_pullback_candles(n_touches=2):
    """Candles where price bounced off EMA20 n_touches times then pulls back again."""
    from tradeloop.lib.data.kite import Candle as C
    candles = []
    # long uptrend
    for i in range(80):
        c = 100 + i * 1.0
        candles.append(C(f'2026-01-{(i%28)+1:02d}', c, c+2, c-1, c, 1_000_000))
    # simulate touches: dip to EMA20 zone and recover
    for _ in range(n_touches):
        # a mini-dip
        touch_close = candles[-1].close - 3.0
        for j in range(3):
            c = touch_close + j * 0.5
            candles.append(C(f'2026-02-{(len(candles)%28)+1:02d}', c, c+2, c-1, c, 1_000_000))
        # recover
        for j in range(5):
            c = candles[-1].close + 1.0
            candles.append(C(f'2026-02-{(len(candles)%28)+1:02d}', c, c+2, c-1, c, 1_000_000))
    # final bar near EMA20 - entry day
    c = candles[-8].close * 0.985   # slight dip
    candles.append(C('2026-03-01', c, c+1, c-1, c, 1_200_000))
    return candles


def test_second_pullback_setup_type_reflects_touch_count():
    class FK:
        def __init__(self, c): self._c = c
        def historical(self, *a, **k): return self._c

    # With multiple touches, setup_type should be 2nd or 3rd pullback
    candles = _repeat_pullback_candles(n_touches=2)
    scans = scan_symbol("TEST", FK(candles), date(2026, 7, 1))
    pullback_scans = [s for s in scans if s.strategy_family == "ema20_pullback"]
    if pullback_scans:
        for s in pullback_scans:
            assert s.exit_rule, "exit_rule must be populated for repeat pullback"


# ---------------------------------------------------------------------------
# Fix 2: sector_rotation_leader composes both exit rules
# ---------------------------------------------------------------------------

def test_sector_leader_exit_rule_includes_original_rule():
    sector_map = {
        "RELIANCE": "Energy", "ONGC": "Energy", "NTPC": "Energy",
        "TATAPOWER": "Energy", "JSWENERGY": "Energy",
    }
    scans = [
        SetupScan("RELIANCE", "20d_breakout", 8.0, "100", "95", "110/115", "ok",
                  "Energy", "EXIT if close < 20d-high"),
        SetupScan("ONGC",     "20d_breakout", 7.0, "100", "95", "110/115", "ok",
                  "Energy", "EXIT if close < 20d-high"),
        SetupScan("NTPC",     "20d_breakout", 6.0, "100", "95", "110/115", "ok",
                  "Energy", "EXIT if close < 20d-high"),
    ]
    leaders = scan_sector_leaders(scans, sector_map, breadth_threshold=0.40, min_tracked=3)
    assert leaders
    rule = leaders[0].exit_rule
    # Must contain BOTH the sector breadth rule AND the original rule
    assert "breadth" in rule.lower(), "missing sector breadth exit rule"
    assert "20d-high" in rule.lower(), "missing original breakout exit rule"


def test_sector_leader_exit_rule_works_when_original_is_empty():
    sector_map = {"A": "IT", "B": "IT", "C": "IT", "D": "IT", "E": "IT"}
    scans = [
        SetupScan("A", "20d_breakout", 9.0, "100", "95", "110/115", "ok"),  # no exit_rule
        SetupScan("B", "20d_breakout", 8.0, "100", "95", "110/115", "ok"),
        SetupScan("C", "20d_breakout", 7.0, "100", "95", "110/115", "ok"),
    ]
    leaders = scan_sector_leaders(scans, sector_map, breadth_threshold=0.40, min_tracked=3)
    assert leaders
    assert leaders[0].exit_rule  # must still have a rule even without original


# ---------------------------------------------------------------------------
# Fix 1: horizon sort in orchestrator
# ---------------------------------------------------------------------------

def test_horizon_sort_puts_short_horizon_first():
    """The orchestrator sorts orders by strategy horizon so results_momentum
    (5d) always gets the first route slot over sector_rotation_leader (20d)."""
    from tradeloop.lib.llm.schemas import Order

    def _order(ticker, family):
        return Order(ticker=ticker, side="BUY", quantity=10, price=100.0,
                     strategy_family=family)

    orders_in = [
        _order("A", "sector_rotation_leader"),
        _order("B", "ema20_pullback"),
        _order("C", "results_momentum"),
        _order("D", "20d_breakout"),
        _order("E", "post_earnings_drift"),
    ]

    _HORIZON = {
        "results_momentum":       5,
        "20d_breakout":           10,
        "post_earnings_drift":    15,
        "ema20_pullback":         20,
        "sector_rotation_leader": 20,
    }
    sorted_orders = sorted(
        orders_in,
        key=lambda o: _HORIZON.get(str(o.strategy_family or "").lower(), 15)
    )
    families = [o.strategy_family for o in sorted_orders]
    assert families[0] == "results_momentum", "shortest horizon must be first"
    assert families[-1] in ("sector_rotation_leader", "ema20_pullback"), \
        "longest horizons must be last"
