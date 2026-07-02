from dataclasses import dataclass
from pathlib import Path
import re
import time
import urllib.request
from typing import Dict


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    source: str
    metrics: Dict[str, float | str]
    available: bool
    note: str


def fetch_fundamentals(symbol: str, cache_dir: Path | None = None, max_cache_age_days: int = 7, polite_delay_seconds: float = 3.0) -> FundamentalSnapshot:
    normalized = symbol.strip().upper()
    cache_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{normalized}.html"
        if cache_path.exists() and _cache_fresh(cache_path, max_cache_age_days):
            return _snapshot_from_html(normalized, cache_path.read_text(encoding="utf-8", errors="ignore"), "screener_cache")

    time.sleep(max(0.0, polite_delay_seconds))
    url = f"https://www.screener.in/company/{normalized}/consolidated/"
    request = urllib.request.Request(url, headers={"User-Agent": "TradeLoop research cache/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return FundamentalSnapshot(normalized, "screener_in", {}, False, f"fundamentals_unavailable: {exc}")
    if cache_path is not None:
        cache_path.write_text(html, encoding="utf-8")
    return _snapshot_from_html(normalized, html, "screener_in")


def _cache_fresh(path: Path, max_age_days: int) -> bool:
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_age_days * 86400


def _snapshot_from_html(symbol: str, html: str, source: str) -> FundamentalSnapshot:
    metrics: Dict[str, float | str] = {}
    for label, key in [
        ("Stock P/E", "pe"),
        ("Book Value", "book_value"),
        ("ROCE", "roce"),
        ("ROE", "roe"),
        ("Debt to equity", "debt_to_equity"),
        ("Promoter holding", "promoter_holding"),
    ]:
        value = _extract_metric(html, label)
        if value is not None:
            metrics[key] = value
    return FundamentalSnapshot(
        symbol=symbol,
        source=source,
        metrics=metrics,
        available=bool(metrics),
        note="ok" if metrics else "no_metrics_extracted",
    )


def _extract_metric(html: str, label: str) -> float | None:
    pattern = rf"{re.escape(label)}.*?<span[^>]*class=\"number\"[^>]*>\s*([-+]?\d+(?:\.\d+)?)"
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    return float(match.group(1)) if match else None
