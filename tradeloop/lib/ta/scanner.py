"""Technical scanner: per-symbol setup detection + universe-level sector leaders.

Five strategy families are implemented:
  20d_breakout          - 20-day high breakout, enter on first pullback to level
  ema20_pullback        - EMA20 pullback in established uptrend (stack intact)
  post_earnings_drift   - unfilled gap-up (>3 %, 2x vol) detected 1-3 days ago
  results_momentum      - today's candle is a results-day gap (>5 %, 3x vol, bullish close)
  sector_rotation_leader- highest-scoring setup in a sector with >= BREADTH_THRESHOLD

Every SetupScan carries:
  strategy_family  - matches strategy_families.yaml id
  exit_rule        - one-line sell condition for the holdings reviewer

Exit rules (also codified in 15_holdings_reviewer.md):
  20d_breakout        : EXIT if close < 20d-high-at-entry; TRIM at T1(2R), EXIT at T2(3R)
  ema20_pullback      : EXIT if close < EMA50; tighten to BE at T1(2R), EXIT at T2(3R)
  post_earnings_drift : EXIT if gap fills (close < gap-open); TRIM at T1(2R) day 5+; EXIT day 15
  results_momentum    : EXIT if close < lower 50pct of gap candle; hard EXIT by day 5
  sector_rotation_leader: EXIT if sector breadth < 30pct OR close < EMA50; tighten at T1(2R)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import yaml

from tradeloop.lib.data.kite import Candle, KiteAuthError
from tradeloop.lib.ta.indicators import add_indicators
from tradeloop.lib.ta.patterns import (
    breakout,
    bullish_close,
    earnings_gap_up,
    ema20_touch_count,
    pullback,
    volume_spike,
)

log = logging.getLogger("tradeloop.scanner")

# Minimum fraction of sector names with a setup for that sector to be "in rotation"
SECTOR_BREADTH_THRESHOLD = 0.40   # 40 % of tracked names must have a setup
SECTOR_MIN_TRACKED = 3            # need at least this many tracked names per sector


@dataclass(frozen=True)
class SetupScan:
    ticker: str
    setup_type: str
    cleanliness_score: float
    entry_zone: str
    stop_zone: str
    target_zone: str
    volume_context: str
    # Strategy metadata - default "" for backward compatibility with test fixtures
    # that construct SetupScan without these fields.  The scanner always populates both.
    strategy_family: str = ""
    exit_rule: str = ""


def candles_to_frame(candles: List[Candle]) -> pd.DataFrame:
    return pd.DataFrame({
        "Open":   [c.open  for c in candles],
        "High":   [c.high  for c in candles],
        "Low":    [c.low   for c in candles],
        "Close":  [c.close for c in candles],
        "Volume": [c.volume for c in candles],
    })


# ---------------------------------------------------------------------------
# Per-symbol helpers
# ---------------------------------------------------------------------------

def _targets(entry: float, atr: float) -> str:
    return f"{entry + 3.0 * atr:.2f}/{entry + 4.5 * atr:.2f}"


def _scan_breakout_pullback(
    symbol: str,
    closes: list[float],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    ema20: list,
    ema50: list,
    ema200: list,
    atr_value: float,
    latest: float,
) -> Optional[SetupScan]:
    """Detect 20d_breakout and ema20_pullback setups.  Both existed before;
    this function preserves their exact signal logic but now populates the
    strategy_family and exit_rule fields.

    For ema20_pullback, ema20_touch_count measures how many times the stock
    has bounced off EMA20 in the last 40 bars.  A 2nd or 3rd touch is a
    stronger signal (institutional level defence confirmed) and boosts the
    cleanliness_score by 1-2 points."""
    breakout_sig = breakout(closes, 20)
    pullback_sig  = pullback(closes, ema20)
    vol_sig       = volume_spike(volumes, 20) if volumes else None

    setup_type = ""
    score = 0.0
    if breakout_sig.bullish:
        setup_type = "20d_breakout"
        score += 6
    if pullback_sig.bullish:
        setup_type = setup_type or "ema20_pullback"
        score += 4
    if vol_sig and vol_sig.bullish:
        score += 2
    if score <= 0:
        return None

    stop = latest - (1.5 * atr_value)
    vol_ctx = vol_sig.reason if vol_sig else "volume_unavailable"

    if setup_type == "20d_breakout":
        family = "20d_breakout"
        exit_rule = (
            "EXIT if close < 20d-high-at-entry (failed breakout) or hard stop; "
            "TRIM 50pct at T1(2R), EXIT remaining at T2(3R)"
        )
    else:
        # Count how many times price has bounced off EMA20 recently.
        # 2nd+ touch means institutional buyers are actively defending the level.
        n_touches = ema20_touch_count(lows, closes, ema20, lookback=40, touch_pct=0.02)
        if n_touches >= 3:
            score += 2
            setup_type = "ema20_3rd_pullback"
            touch_note = "3rd confirmed EMA20 bounce; institutional level strongly defended"
        elif n_touches >= 2:
            score += 1
            setup_type = "ema20_2nd_pullback"
            touch_note = "2nd confirmed EMA20 bounce; level building track record"
        else:
            touch_note = "1st touch at EMA20"
        family = "ema20_pullback"
        exit_rule = (
            f"EXIT if close < EMA50 (uptrend broken) or hard stop [{touch_note}]; "
            "TIGHTEN_STOP to breakeven at T1(2R), EXIT at T2(3R)"
        )

    return SetupScan(
        ticker=symbol.strip().upper(),
        setup_type=setup_type,
        strategy_family=family,
        cleanliness_score=round(min(score, 10), 2),
        entry_zone=f"{latest:.2f}",
        stop_zone=f"{stop:.2f}",
        target_zone=_targets(latest, atr_value),
        volume_context=vol_ctx,
        exit_rule=exit_rule,
    )


def _scan_post_earnings_drift(
    symbol: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    atr_value: float,
    latest: float,
) -> Optional[SetupScan]:
    """Detect a post-earnings drift setup: unfilled gap-up 1-3 days ago
    with >= 2x average volume.  Entry is current close; stop is the gap-open
    minus half ATR (if the gap fills, the thesis is dead).

    Returns None if the gap-up has already been scored as a results_momentum
    setup (results day is today's candle, not yesterday's).
    """
    gap_sig = earnings_gap_up(opens, closes, volumes,
                              lookback=3, min_gap_pct=3.0, volume_multiple=2.0)
    if not gap_sig.bullish:
        return None

    # Reject if the gap happened on today's candle (that is results_momentum territory)
    vol_lookback = 20
    if len(volumes) >= vol_lookback + 1:
        avg_vol = sum(float(v) for v in volumes[-vol_lookback - 1: -1]) / vol_lookback
        today_gap_pct = (float(opens[-1]) / float(closes[-2]) - 1) * 100 if len(closes) >= 2 else 0
        today_vol_ok  = float(volumes[-1]) >= avg_vol * 3.0
        if today_gap_pct >= 5.0 and today_vol_ok:
            return None  # hand off to results_momentum

    # Stop: gap-day's open - ATR/2  (recover gap_open from the reason string is unreliable;
    # use ATR-based stop below the current price instead - simpler and safer)
    stop  = latest - (1.5 * atr_value)
    score = 8.0  # high because gap + volume is strong evidence

    exit_rule = (
        "EXIT if gap fills (close < gap-open day's open) or hard stop; "
        "TRIM 50pct at T1(2R) if holding 5+ days; hard EXIT at day 15"
    )
    return SetupScan(
        ticker=symbol.strip().upper(),
        setup_type="post_earnings_drift",
        strategy_family="post_earnings_drift",
        cleanliness_score=round(min(score, 10), 2),
        entry_zone=f"{latest:.2f}",
        stop_zone=f"{stop:.2f}",
        target_zone=_targets(latest, atr_value),
        volume_context=gap_sig.reason,
        exit_rule=exit_rule,
    )


def _scan_results_momentum(
    symbol: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    atr_value: float,
    latest: float,
) -> Optional[SetupScan]:
    """Detect a results-day momentum setup: TODAY's candle has a large gap (>= 5 %)
    with >= 3x volume AND a bullish close (top 50 % of range).

    Entry: current close. Stop: results-day low (micro-stop).
    Target: generous because momentum plays can run hard.
    """
    if len(closes) < 2 or len(volumes) < 21:
        return None

    vol_lookback = 20
    avg_vol = sum(float(v) for v in volumes[-vol_lookback - 1: -1]) / vol_lookback
    if avg_vol <= 0:
        return None

    today_gap_pct = (float(opens[-1]) / float(closes[-2]) - 1) * 100
    today_vol_x   = float(volumes[-1]) / avg_vol

    if today_gap_pct < 5.0 or today_vol_x < 3.0:
        return None

    bull_close_sig = bullish_close(opens, highs, lows, closes, min_range_position=0.50)
    if not bull_close_sig.bullish:
        return None

    # Stop is the results-day low (if it breaks, momentum is gone)
    stop = float(lows[-1]) - 0.5 * atr_value
    score = min(6.0 + min(today_vol_x / 3.0, 2.0) + (1.0 if today_gap_pct >= 8.0 else 0.0), 10.0)

    exit_rule = (
        "EXIT if close < lower 50pct of results-day candle or hard stop; "
        "TRIM at T1(2R); hard EXIT by day 5"
    )
    return SetupScan(
        ticker=symbol.strip().upper(),
        setup_type="results_momentum",
        strategy_family="results_momentum",
        cleanliness_score=round(score, 2),
        entry_zone=f"{latest:.2f}",
        stop_zone=f"{stop:.2f}",
        target_zone=_targets(latest, atr_value),
        volume_context=f"gap_{today_gap_pct:.1f}pct_vol_{today_vol_x:.1f}x",
        exit_rule=exit_rule,
    )


# ---------------------------------------------------------------------------
# Universe-level: sector rotation leaders
# ---------------------------------------------------------------------------

def _load_sector_map(config_dir: Path) -> Dict[str, str]:
    """Return {SYMBOL: sector_name} from sector_map.yaml.  Missing file → {}."""
    path = Path(config_dir) / "sector_map.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    result: Dict[str, str] = {}
    for sector, symbols in (data.get("sectors") or {}).items():
        for sym in (symbols or []):
            result[str(sym).strip().upper()] = sector
    return result


def scan_sector_leaders(
    scans: List[SetupScan],
    sector_map: Dict[str, str],
    breadth_threshold: float = SECTOR_BREADTH_THRESHOLD,
    min_tracked: int = SECTOR_MIN_TRACKED,
) -> List[SetupScan]:
    """Given the full per-symbol scan results, identify sectors in rotation
    and return one SetupScan per leading sector name.

    A sector is "in rotation" when >= breadth_threshold fraction of its
    tracked symbols (those present in sector_map) have a setup signal.
    The leader is the symbol with the highest cleanliness_score in that sector.

    Symbols already present in `scans` are not duplicated - their existing
    SetupScan is annotated with strategy_family='sector_rotation_leader' only
    if they are the sector leader.  New entries are created for leaders that
    already have an existing scan (we REPLACE their entry with an upgraded one).
    """
    if not sector_map:
        return []

    # Build a set of scanned tickers and a score look-up
    scanned: Dict[str, SetupScan] = {s.ticker.upper(): s for s in scans}

    # Group sector_map symbols by sector and count which have a setup
    from collections import defaultdict
    sector_all: Dict[str, List[str]]   = defaultdict(list)   # all tracked
    sector_hits: Dict[str, List[str]]  = defaultdict(list)   # those with setups

    for sym, sector in sector_map.items():
        sector_all[sector].append(sym)
        if sym.upper() in scanned:
            sector_hits[sector].append(sym.upper())

    leaders: List[SetupScan] = []
    for sector, tracked in sector_all.items():
        if len(tracked) < min_tracked:
            continue
        breadth = len(sector_hits[sector]) / len(tracked)
        if breadth < breadth_threshold:
            continue

        # Pick the highest-scoring setup in this sector
        candidates = [scanned[sym] for sym in sector_hits[sector] if sym in scanned]
        if not candidates:
            continue
        best = max(candidates, key=lambda s: s.cleanliness_score)

        exit_rule = (
            f"EXIT if sector breadth < 30pct ({sector}) or close < EMA50; "
            "TIGHTEN_STOP to breakeven at T1(2R), EXIT at T2(3R); "
            f"ALSO APPLY original setup rule: {best.exit_rule}"
            if best.exit_rule else
            f"EXIT if sector breadth < 30pct ({sector}) or close < EMA50; "
            "TIGHTEN_STOP to breakeven at T1(2R), EXIT at T2(3R)"
        )
        leaders.append(SetupScan(
            ticker=best.ticker,
            setup_type=f"sector_rotation_leader_{sector.replace(' ', '_').lower()}",
            strategy_family="sector_rotation_leader",
            cleanliness_score=min(best.cleanliness_score + 1.0, 10.0),  # +1 for sector context
            entry_zone=best.entry_zone,
            stop_zone=best.stop_zone,
            target_zone=best.target_zone,
            volume_context=f"sector_breadth_{breadth:.0%}_in_{sector}",
            exit_rule=exit_rule,
        ))

    return leaders


# ---------------------------------------------------------------------------
# Main per-symbol entry point
# ---------------------------------------------------------------------------

def scan_symbol(
    symbol: str,
    kite_client,
    as_of: date,
    min_turnover_inr: float = 0.0,
    min_stop_pct: float = 0.0,
) -> List[SetupScan]:
    """Scan a single symbol and return all strategy setups detected.

    Returns a list (not a single item) because a symbol may qualify for more
    than one strategy simultaneously (e.g. it gapped up AND is on EMA20).
    Returns [] when the symbol fails data or liquidity checks.
    """
    frm = as_of - timedelta(days=200)
    candles = kite_client.historical(symbol, frm, as_of, "day")
    if len(candles) < 30:
        return []

    enriched = add_indicators(candles_to_frame(candles))
    closes  = [float(v) for v in enriched["Close"].tolist()]
    opens_  = [float(v) for v in enriched["Open"].tolist()]   if "Open"   in enriched.columns else []
    highs_  = [float(v) for v in enriched["High"].tolist()]   if "High"   in enriched.columns else []
    lows_   = [float(v) for v in enriched["Low"].tolist()]    if "Low"    in enriched.columns else []
    volumes = [float(v) for v in enriched["Volume"].tolist()] if "Volume" in enriched.columns else []
    ema20   = enriched["EMA20"].tolist()
    ema50   = enriched["EMA50"].tolist()
    ema200  = enriched["EMA200"].tolist()

    atr_series = enriched["ATR14"].dropna() if "ATR14" in enriched.columns else pd.Series(dtype=float)
    if atr_series.empty:
        return []

    # Liquidity floor
    if min_turnover_inr > 0 and volumes:
        turnover = sum(c * v for c, v in zip(closes, volumes)) / len(closes)
        if turnover < min_turnover_inr:
            return []

    atr_value = float(atr_series.iloc[-1])
    latest    = closes[-1]

    # Minimum-volatility floor (rejects near-zero-vol cash ETFs)
    if min_stop_pct > 0 and latest > 0 and (1.5 * atr_value) / latest < min_stop_pct:
        return []

    results: List[SetupScan] = []

    # --- Results-day momentum (most urgent - check first) ---
    if opens_ and highs_ and lows_:
        rm = _scan_results_momentum(symbol, opens_, highs_, lows_, closes, volumes, atr_value, latest)
        if rm is not None:
            results.append(rm)

    # --- Post-earnings drift (gap 1-3 days ago, not today) ---
    if opens_:
        ped = _scan_post_earnings_drift(symbol, opens_, highs_ or [], lows_ or [],
                                        closes, volumes, atr_value, latest)
        if ped is not None:
            results.append(ped)

    # --- 20d breakout / EMA20 pullback (always run) ---
    bp = _scan_breakout_pullback(
        symbol, closes, opens_, highs_, lows_, volumes,
        ema20, ema50, ema200, atr_value, latest
    )
    if bp is not None:
        results.append(bp)

    return results


# ---------------------------------------------------------------------------
# Universe scan (called by ingest.run)
# ---------------------------------------------------------------------------

# Expected, per-symbol data problems we tolerate; anything else is a real bug.
_TOLERATED = (ValueError, RuntimeError)


def scan_universe(
    symbols: Iterable[str],
    kite_client,
    as_of: date,
    max_fetch: int = 2500,
    min_turnover_inr: float = 0.0,
    pace_seconds: float = 0.0,
    sleep=time.sleep,
    min_stop_pct: float = 0.0,
    config_dir: "Path | None" = None,
) -> List[SetupScan]:
    """Scan every symbol and append sector-rotation leaders.

    Returns a deduplicated, score-sorted list.  When a symbol qualifies for
    multiple strategies the highest-scoring one is kept (sector_rotation_leader
    always beats a tie since it gets +1 to score).
    """
    scans: List[SetupScan] = []
    for symbol in list(symbols)[:max_fetch]:
        if pace_seconds > 0:
            sleep(pace_seconds)
        try:
            hits = scan_symbol(symbol, kite_client, as_of,
                               min_turnover_inr=min_turnover_inr,
                               min_stop_pct=min_stop_pct)
        except KiteAuthError:
            raise
        except _TOLERATED as exc:
            log.warning("scan skipped %s: %s", symbol, exc)
            continue
        scans.extend(hits)

    # Deduplicate: keep the highest-scoring setup per ticker
    best: Dict[str, SetupScan] = {}
    for s in scans:
        key = s.ticker.upper()
        if key not in best or s.cleanliness_score > best[key].cleanliness_score:
            best[key] = s
    unique = list(best.values())

    # Sector rotation leaders (universe-level pass)
    sector_map: Dict[str, str] = {}
    if config_dir is not None:
        sector_map = _load_sector_map(Path(config_dir))
    if sector_map:
        leaders = scan_sector_leaders(unique, sector_map)
        # Upgrade or add: replace existing entry for the same ticker if leader score is higher
        for leader in leaders:
            key = leader.ticker.upper()
            if key not in best or leader.cleanliness_score >= best[key].cleanliness_score:
                best[key] = leader
        unique = list(best.values())

    unique.sort(key=lambda s: s.cleanliness_score, reverse=True)
    return unique
