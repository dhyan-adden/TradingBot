from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List

import pandas as pd

from tradeloop.lib.data.kite import Candle
from tradeloop.lib.ta.indicators import add_indicators
from tradeloop.lib.ta.patterns import breakout, pullback, volume_spike

log = logging.getLogger("tradeloop.scanner")


@dataclass(frozen=True)
class SetupScan:
    ticker: str
    setup_type: str
    cleanliness_score: float
    entry_zone: str
    stop_zone: str
    target_zone: str
    volume_context: str


def candles_to_frame(candles: List[Candle]) -> pd.DataFrame:
    return pd.DataFrame({
        "Open": [c.open for c in candles],
        "High": [c.high for c in candles],
        "Low": [c.low for c in candles],
        "Close": [c.close for c in candles],
        "Volume": [c.volume for c in candles],
    })


def scan_symbol(symbol: str, kite_client, as_of: date, min_turnover_inr: float = 0.0) -> "SetupScan | None":
    frm = as_of - timedelta(days=200)
    candles = kite_client.historical(symbol, frm, as_of, "day")
    if len(candles) < 30:
        return None
    enriched = add_indicators(candles_to_frame(candles))
    closes = [float(v) for v in enriched["Close"].tolist()]
    volumes = [float(v) for v in enriched["Volume"].tolist()] if "Volume" in enriched.columns else []
    ema20 = enriched["EMA20"].tolist()
    atr_series = enriched["ATR14"].dropna() if "ATR14" in enriched.columns else pd.Series(dtype=float)
    if atr_series.empty:
        return None  # no fabricated stop - a setup without a real ATR is not tradeable
    # liquidity floor: mean daily traded value must clear the configured threshold
    if min_turnover_inr > 0 and volumes:
        turnover = sum(c * v for c, v in zip(closes, volumes)) / len(closes)
        if turnover < min_turnover_inr:
            return None
    atr_value = float(atr_series.iloc[-1])
    latest = closes[-1]
    breakout_signal = breakout(closes, 20)
    pullback_signal = pullback(closes, ema20)
    volume_signal = volume_spike(volumes, 20) if volumes else None
    setup_type = ""
    score = 0.0
    if breakout_signal.bullish:
        setup_type = "20d_breakout"
        score += 6
    if pullback_signal.bullish:
        setup_type = setup_type or "ema20_pullback"
        score += 4
    if volume_signal and volume_signal.bullish:
        score += 2
    if score <= 0:
        return None
    return SetupScan(
        ticker=symbol.strip().upper(),
        setup_type=setup_type,
        cleanliness_score=round(min(score, 10), 2),
        entry_zone=f"{latest:.2f}",
        stop_zone=f"{latest - (1.5 * atr_value):.2f}",
        target_zone=f"{latest + (2.0 * atr_value):.2f}/{latest + (3.0 * atr_value):.2f}",
        volume_context=volume_signal.reason if volume_signal else "volume_unavailable",
    )


# expected, per-symbol data problems we tolerate; anything else is a real bug and propagates.
# (LookupError/KeyError is NOT included - a KeyError means a programming bug, not a data
# problem, and must propagate rather than be swallowed as "just this symbol was bad".)
_TOLERATED = (ValueError, RuntimeError)


def scan_universe(symbols: Iterable[str], kite_client, as_of: date, max_fetch: int = 2500,
                  min_turnover_inr: float = 0.0, pace_seconds: float = 0.0,
                  sleep=time.sleep) -> List["SetupScan"]:
    scans: List[SetupScan] = []
    for symbol in list(symbols)[:max_fetch]:
        if pace_seconds > 0:
            sleep(pace_seconds)  # respect Kite ~3 req/s
        try:
            scan = scan_symbol(symbol, kite_client, as_of, min_turnover_inr=min_turnover_inr)
        except _TOLERATED as exc:
            log.warning("scan skipped %s: %s", symbol, exc)
            continue
        if scan is not None:
            scans.append(scan)
    scans.sort(key=lambda item: item.cleanliness_score, reverse=True)
    return scans


from tradeloop.lib.data.snapshot import render_setups  # noqa: E402  backward-compat re-export
