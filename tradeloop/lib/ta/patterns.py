from dataclasses import dataclass
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
