from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

# Max fractional deviation an order's entry/hard_stop may sit from the scanner's
# real level before it is treated as ungrounded (fabricated). Tick-rounding and a
# small limit offset stay within this; a news-anchored or stale-frame number does
# not. ponytail: single constant - move to settings.yaml only if it needs tuning.
GROUNDING_TOLERANCE = 0.02


@dataclass
class GroundingResult:
    ok: bool
    violations: List[Tuple[str, str]] = field(default_factory=list)  # (ticker, reason)


def _get(order, key):
    return order.get(key) if isinstance(order, dict) else getattr(order, key, None)


def load_scan_levels(run_dir: Path) -> Dict[str, dict]:
    """Rehydrate the frozen scanner levels {TICKER: {entry, stop}} from the
    snapshot's setup records. Empty dict when there is no snapshot or no setups
    (dormant scan) - the caller then skips grounding, like the evidence gate."""
    items = Path(run_dir) / "snapshot" / "items.jsonl"
    if not items.exists():
        return {}
    levels: Dict[str, dict] = {}
    for line in items.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind") != "setup":
            continue
        try:
            levels[str(rec["ticker"]).strip().upper()] = {
                "entry": float(rec["entry_zone"]),
                "stop": float(rec["stop_zone"]),
            }
        except (KeyError, ValueError, TypeError):
            continue
    return levels


def _off(value: float, ref: float) -> float:
    return abs(value - ref) / ref if ref else float("inf")


def validate_grounding(orders, scan_levels: Dict[str, dict],
                       tol: float = GROUNDING_TOLERANCE) -> GroundingResult:
    """Every NEW BUY order's entry (price) and hard_stop must sit within `tol`
    of the scanner's real level for that ticker. A ticker absent from the scan
    has no real stop and cannot be sized, so it is a violation. This makes the
    price grounding deterministic instead of trusting the model to obey the
    prompt. Long-only system: SELL orders are exits priced at the live LTP by
    the deterministic holdings path, never model-invented, so they are exempt."""
    violations: List[Tuple[str, str]] = []
    for order in orders:
        side = str(_get(order, "side") or "").strip().upper()
        if side == "SELL":
            continue
        ticker = str(_get(order, "ticker") or "").strip().upper()
        lvl = scan_levels.get(ticker)
        if lvl is None:
            violations.append((ticker, "no scan setup for this ticker"))
            continue
        entry = _get(order, "price")
        stop = _get(order, "hard_stop")
        if entry is None or _off(float(entry), lvl["entry"]) > tol:
            violations.append(
                (ticker, f"entry {entry} off scan {lvl['entry']} by >{tol:.0%}"))
        if stop is None or _off(float(stop), lvl["stop"]) > tol:
            violations.append(
                (ticker, f"hard_stop {stop} off scan {lvl['stop']} by >{tol:.0%}"))
    return GroundingResult(ok=not violations, violations=violations)
