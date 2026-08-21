"""Phase 6: single source of truth for live promotion.

Centralizes the readiness logic that `router.live_promotion_ready()` used to read
out of a markdown performance report. Trade metrics come from the global ledger
(`state/ledger.db` ORDER_FILLED events); the audit gate scans every routed run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from tradeloop.lib.audit.attribution import portfolio_stats_from_fills
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger, LedgerTamperError
from tradeloop.lib.config import Settings

_CRITICAL_SEVERITIES = ("material_weakness", "significant_deficiency")


@dataclass(frozen=True)
class PromotionStatus:
    ready: bool
    reasons: List[str]
    closed_paper_trades: int
    win_rate: float
    expectancy_r: float
    max_drawdown_r: float
    clean_audits: bool


def _load_settings(root: Path, settings: Settings | None) -> Settings:
    if settings is not None:
        return settings
    from tradeloop.lib.config import load_settings
    return load_settings(root / "config" / "settings.yaml")


def _audits_clean(root: Path) -> bool:
    """Strict for this batch: every routed run (non-empty fills.json) must be
    audit-clean - no audit_error.txt, a controls.json with no critical severity,
    and a 40_reconcile.md that reports `clean: all sources agree`."""
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return True
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        fills_path = run_dir / "fills.json"
        if not fills_path.exists():
            continue
        try:
            fills = json.loads(fills_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        if not fills:  # empty placeholder, not a routed run
            continue
        if (run_dir / "audit_error.txt").exists():
            return False
        controls_path = run_dir / "controls.json"
        if not controls_path.exists():
            return False
        try:
            controls = json.loads(controls_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        for d in controls.get("deficiencies", []):
            if str(d.get("severity", "")) in _CRITICAL_SEVERITIES:
                return False
        reconcile = run_dir / "40_reconcile.md"
        if not reconcile.exists():
            return False
        if "clean: all sources agree" not in reconcile.read_text(encoding="utf-8"):
            return False
    return True


def evaluate_live_promotion(root: Path, settings: Settings | None = None) -> PromotionStatus:
    root = Path(root)
    settings = _load_settings(root, settings)
    reasons: List[str] = []

    ledger_path = root / "state" / "ledger.db"
    if not ledger_path.exists():
        return PromotionStatus(False, ["no ledger found"], 0, 0.0, 0.0, 0.0, False)
    ledger = Ledger(ledger_path)
    try:
        ledger.verify_chain()
    except LedgerTamperError:
        return PromotionStatus(False, ["ledger chain tampered"], 0, 0.0, 0.0, 0.0, False)

    stats = portfolio_stats_from_fills(ledger.replay([ORDER_FILLED]))
    if stats.closed_trades < settings.promotion_min_closed_paper_trades:
        reasons.append(
            f"closed_paper_trades={stats.closed_trades} < "
            f"{settings.promotion_min_closed_paper_trades}")
    if stats.closed_trades >= 1 and stats.win_rate < settings.promotion_min_win_rate:
        reasons.append(f"win_rate={stats.win_rate} < {settings.promotion_min_win_rate}")
    if stats.closed_trades >= 1 and stats.expectancy_r < settings.promotion_min_expectancy_r:
        reasons.append(
            f"expectancy_r={stats.expectancy_r} < {settings.promotion_min_expectancy_r}")
    if stats.max_drawdown_r > settings.promotion_max_drawdown_r:
        reasons.append(
            f"max_drawdown_r={stats.max_drawdown_r} > {settings.promotion_max_drawdown_r}")

    require_audits = settings.promotion_require_clean_audits
    clean = _audits_clean(root) if require_audits else True
    if require_audits and not clean:
        reasons.append("audit gate not clean")

    return PromotionStatus(
        ready=not reasons,
        reasons=reasons,
        closed_paper_trades=stats.closed_trades,
        win_rate=stats.win_rate,
        expectancy_r=stats.expectancy_r,
        max_drawdown_r=stats.max_drawdown_r,
        clean_audits=clean,
    )
