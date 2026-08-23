from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class PatternSignal:
    name: str
    bullish: bool
    reason: str


def breakout(closes: Sequence[float], lookback: int = 20) -> PatternSignal:
    if lookback <= 1:
        raise ValueError("lookback must be greater than 1")
    if len(closes) <= lookback:
        return PatternSignal("breakout", False, "insufficient_history")
    previous_high = max(float(value) for value in closes[-lookback - 1 : -1])
    latest = float(closes[-1])
    return PatternSignal("breakout", latest > previous_high, "latest_close_above_lookback_high" if latest > previous_high else "no_breakout")


def pullback(closes: Sequence[float], ema_values: Sequence[float | None]) -> PatternSignal:
    if not closes or not ema_values or ema_values[-1] is None:
        return PatternSignal("pullback", False, "insufficient_history")
    latest = float(closes[-1])
    average = float(ema_values[-1])
    near_average = abs(latest - average) / average <= 0.015 if average else False
    trend_up = len(ema_values) >= 3 and ema_values[-3] is not None and float(ema_values[-1]) > float(ema_values[-3])
    return PatternSignal("pullback", bool(near_average and trend_up), "near_rising_ema" if near_average and trend_up else "no_bullish_pullback")


def gap_up(opens: Sequence[float], previous_closes: Sequence[float], min_gap_pct: float = 1.0) -> PatternSignal:
    if not opens or not previous_closes:
        return PatternSignal("gap_up", False, "insufficient_history")
    previous_close = float(previous_closes[-1])
    if previous_close <= 0:
        return PatternSignal("gap_up", False, "invalid_previous_close")
    gap_pct = ((float(opens[-1]) - previous_close) / previous_close) * 100
    return PatternSignal("gap_up", gap_pct >= min_gap_pct, "gap_up_threshold_met" if gap_pct >= min_gap_pct else "gap_too_small")


def volume_spike(volumes: Sequence[float], lookback: int = 20, multiple: float = 2.0) -> PatternSignal:
    if len(volumes) <= lookback:
        return PatternSignal("volume_spike", False, "insufficient_history")
    average = sum(float(value) for value in volumes[-lookback - 1 : -1]) / lookback
    latest = float(volumes[-1])
    return PatternSignal("volume_spike", latest >= average * multiple, "volume_above_threshold" if latest >= average * multiple else "volume_normal")


def inside_bar(highs: Sequence[float], lows: Sequence[float]) -> PatternSignal:
    if len(highs) < 2 or len(lows) < 2:
        return PatternSignal("inside_bar", False, "insufficient_history")
    bullish = float(highs[-1]) < float(highs[-2]) and float(lows[-1]) > float(lows[-2])
    return PatternSignal("inside_bar", bullish, "inside_prior_bar" if bullish else "not_inside_bar")


def earnings_gap_up(
    opens: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    lookback: int = 3,
    min_gap_pct: float = 3.0,
    volume_multiple: float = 2.0,
) -> PatternSignal:
    """Detects a significant gap-up in the last `lookback` candles with above-average
    volume - the daily OHLCV signature of a post-earnings jump.

    Returns bullish=True when ALL of:
      - An open in the last lookback bars gapped up >= min_gap_pct vs the prior close
      - Volume on that day was >= volume_multiple × 20-day average volume
      - The current close is ABOVE that gap-open (gap not yet filled)
    Also returns the index offset of the gap bar (0 = yesterday, 1 = two days ago).
    """
    vol_lookback = 20
    n = len(closes)
    if n < vol_lookback + 1 or len(opens) < n or len(volumes) < n:
        return PatternSignal("earnings_gap_up", False, "insufficient_history")
    avg_vol = sum(float(v) for v in volumes[-vol_lookback - 1: -1]) / vol_lookback
    if avg_vol <= 0:
        return PatternSignal("earnings_gap_up", False, "zero_average_volume")
    current_close = float(closes[-1])
    # Scan the last `lookback` bars (excluding today) for the gap event
    for offset in range(1, min(lookback + 1, n)):
        gap_open = float(opens[-offset])
        prior_close = float(closes[-offset - 1])
        if prior_close <= 0:
            continue
        gap_pct = (gap_open - prior_close) / prior_close * 100
        gap_vol = float(volumes[-offset])
        if gap_pct >= min_gap_pct and gap_vol >= avg_vol * volume_multiple:
            if current_close >= gap_open:  # gap not filled
                reason = f"gap_{gap_pct:.1f}pct_{offset}d_ago_vol_{gap_vol/avg_vol:.1f}x_unfilled"
                return PatternSignal("earnings_gap_up", True, reason)
    return PatternSignal("earnings_gap_up", False, "no_qualifying_gap")


def bullish_close(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    min_range_position: float = 0.5,
) -> PatternSignal:
    """True when the last candle closed in the upper portion of its range.
    min_range_position=0.5 means close is in the top 50% (above midpoint).
    min_range_position=0.75 means close is in the top 25%.
    Used to confirm momentum on the results-day candle."""
    if not highs or not lows or not closes or not opens:
        return PatternSignal("bullish_close", False, "insufficient_history")
    high = float(highs[-1])
    low = float(lows[-1])
    close = float(closes[-1])
    rng = high - low
    if rng <= 0:
        return PatternSignal("bullish_close", False, "zero_range")
    position = (close - low) / rng  # 0 = closed at low, 1 = closed at high
    bullish = position >= min_range_position
    return PatternSignal(
        "bullish_close",
        bullish,
        f"close_at_{position:.0%}_of_range" if bullish else f"close_only_{position:.0%}_of_range",
    )


def relative_strength_pct(
    closes: Sequence[float],
    benchmark_closes: Sequence[float],
    period: int = 20,
) -> float:
    """Return the stock's performance relative to a benchmark over the last
    `period` bars, as a percentage. Positive = outperforming, negative = lagging.
    Returns 0.0 when either series lacks data."""
    if len(closes) < period + 1 or len(benchmark_closes) < period + 1:
        return 0.0
    stock_ret = (float(closes[-1]) / float(closes[-period - 1]) - 1) * 100
    bench_ret = (float(benchmark_closes[-1]) / float(benchmark_closes[-period - 1]) - 1) * 100
    if float(benchmark_closes[-period - 1]) <= 0:
        return 0.0
    return round(stock_ret - bench_ret, 2)


def ema20_touch_count(
    lows: Sequence[float],
    closes: Sequence[float],
    ema20_vals: Sequence[float],
    lookback: int = 40,
    touch_pct: float = 0.02,
) -> int:
    """Count how many candles in the last `lookback` bars touched EMA20 from above
    (low within touch_pct of EMA20) while closing above it.

    A count of 2+ means the stock has found support at EMA20 multiple times, which
    is a stronger signal than a first touch - institutional buyers are consistently
    defending this level.

    NaN values in ema20_vals (from pandas series) are skipped safely.
    """
    n = len(closes)
    count = 0
    for i in range(max(0, n - lookback), n - 1):   # exclude the most recent bar (that's the entry bar)
        val = ema20_vals[i]
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        ema = float(val)
        if ema <= 0:
            continue
        low  = float(lows[i])
        close = float(closes[i])
        if abs(low - ema) / ema <= touch_pct and close > ema:
            count += 1
    return count
