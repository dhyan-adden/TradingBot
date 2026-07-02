from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from tradeloop.lib.data.nse_quotes import fetch_ohlcv
from tradeloop.lib.ta.indicators import add_indicators
from tradeloop.lib.ta.patterns import breakout, pullback, volume_spike


@dataclass(frozen=True)
class SetupScan:
    ticker: str
    setup_type: str
    cleanliness_score: float
    entry_zone: str
    stop_zone: str
    target_zone: str
    volume_context: str


def scan_symbol(symbol: str, cache_dir: Path | None = None) -> SetupScan | None:
    frame = fetch_ohlcv(symbol, cache_dir=cache_dir)
    if len(frame) < 30:
        return None
    enriched = add_indicators(frame)
    closes = [float(value) for value in enriched["Close"].tolist()]
    volumes = [float(value) for value in enriched["Volume"].tolist()] if "Volume" in enriched.columns else []
    ema20 = enriched["EMA20"].tolist()
    breakout_signal = breakout(closes, 20)
    pullback_signal = pullback(closes, ema20)
    volume_signal = volume_spike(volumes, 20) if volumes else None
    latest = closes[-1]
    atr_value = enriched["ATR14"].dropna().iloc[-1] if "ATR14" in enriched.columns and not enriched["ATR14"].dropna().empty else latest * 0.02
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
        stop_zone=f"{latest - (1.5 * float(atr_value)):.2f}",
        target_zone=f"{latest + (2.0 * float(atr_value)):.2f}/{latest + (3.0 * float(atr_value)):.2f}",
        volume_context=volume_signal.reason if volume_signal else "volume_unavailable",
    )


def scan_universe(symbols: Iterable[str], cache_dir: Path | None = None, limit: int = 30) -> List[SetupScan]:
    scans: List[SetupScan] = []
    for symbol in symbols:
        try:
            scan = scan_symbol(symbol, cache_dir=cache_dir)
        except Exception:
            continue
        if scan is not None:
            scans.append(scan)
    scans.sort(key=lambda item: item.cleanliness_score, reverse=True)
    return scans[:limit]


def render_setups(scans: Iterable[SetupScan]) -> str:
    lines = ["# Raw Technical Setups", ""]
    for scan in scans:
        lines.append(
            f"- {scan.ticker}: {scan.setup_type}, score={scan.cleanliness_score}, "
            f"entry={scan.entry_zone}, stop={scan.stop_zone}, targets={scan.target_zone}, volume={scan.volume_context}"
        )
    lines.append("")
    return "\n".join(lines)

