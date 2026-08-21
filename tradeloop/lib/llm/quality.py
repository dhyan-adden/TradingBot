"""Stage output quality gates.

Small/free analysis models can return hollow or uncited output. We let the
strong paid stages (debate, trade plan, risk, PM) still run, but a weak
research stage degrades safely instead of cascading into a confident trade.

- Soft degradations append a JSON line to ``<run_dir>/analysis_quality.jsonl``
  and do NOT raise, so the run continues but the degradation is visible to the
  downstream manager stages.
- Hard failures raise ``LLMValidationError`` so a bad stage cannot silently
  become an order.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from tradeloop.lib.llm.client import LLMValidationError

SEVERITIES = {"info", "degraded", "hard_block"}
SCOPES = {"new_buys", "all_orders", "research_only"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_quality(run_dir: Path, stage: str, severity: str, scope: str, reason: str) -> None:
    if severity not in SEVERITIES:
        raise ValueError(f"invalid quality severity: {severity}")
    if scope not in SCOPES:
        raise ValueError(f"invalid quality scope: {scope}")
    line = {
        "stage": stage,
        "severity": severity,
        "scope": scope,
        "reason": reason,
        "created_at": _now_iso(),
    }
    path = run_dir / "analysis_quality.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def validate_stage_quality(stage: str, result: BaseModel, run_dir: Path) -> None:
    # Only 41_pm_decision may produce orders; a non-PM stage emitting an orders
    # field is a structural violation that must never reach the broker path.
    if stage != "41_pm_decision" and hasattr(result, "orders"):
        raise LLMValidationError(
            f"{stage}: non-PM stage emitted an 'orders' field; only 41_pm_decision "
            f"may produce orders")

    if stage == "10_news":
        for n in getattr(result, "names_in_play", None) or []:
            tier = getattr(n, "tier", None)
            evidence = getattr(n, "evidence", None) or []
            if tier in ("A", "B") and not evidence:
                append_quality(
                    run_dir, stage, "degraded", "research_only",
                    f"tier-{tier} name {getattr(n, 'ticker', '?')} has no evidence citations")
    elif stage == "14_shortlist":
        for c in getattr(result, "candidates", None) or []:
            track = getattr(c, "source_track", None)
            evidence = getattr(c, "evidence", None) or []
            if track in ("tier_a", "tier_b", "tier_c") and not evidence:
                append_quality(
                    run_dir, stage, "degraded", "research_only",
                    f"news-driven candidate {getattr(c, 'ticker', '?')} has no evidence citations")


def quality_has_hard_block_new_buys(run_dir: Path) -> bool:
    path = run_dir / "analysis_quality.jsonl"
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if rec.get("severity") == "hard_block" and rec.get("scope") == "new_buys":
            return True
    return False
