from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from tradingbot.event_log import EventLog
from tradingbot.memory.projections import content_hash


@dataclass(frozen=True)
class LearningMetrics:
    symbol: str
    trade_id: str
    pnl_inr: float
    pnl_pct: float
    lesson_tags: List[str]


def closed_trade_metrics(payload: Dict) -> LearningMetrics:
    entry_price = float(payload.get("entry_price", payload.get("avg_price", 0)))
    exit_price = float(payload.get("fill_price", payload.get("exit_price", 0)))
    quantity = int(payload.get("quantity", 0))
    pnl = round((exit_price - entry_price) * quantity, 2)
    pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 4) if entry_price else 0.0
    tags = ["exit_discipline_held"] if pnl >= 0 else ["sized_too_large" if quantity > 1 else "stop_too_tight"]
    return LearningMetrics(
        symbol=str(payload.get("symbol", "")),
        trade_id=str(payload.get("order_id", payload.get("trade_id", "unknown"))),
        pnl_inr=pnl,
        pnl_pct=pnl_pct,
        lesson_tags=tags,
    )


class LearningProjector:
    def __init__(self, event_log: EventLog, memory_root: Path):
        self.event_log = event_log
        self.memory_root = memory_root

    def write_rule_lesson(self, metrics: LearningMetrics) -> Path:
        path = self.memory_root / "lessons" / f"LESSON-{metrics.trade_id}.md"
        content = "\n".join(
            [
                "---",
                f"trade_id: {metrics.trade_id}",
                f"symbol: {metrics.symbol}",
                f"pnl_inr: {metrics.pnl_inr}",
                f"pnl_pct: {metrics.pnl_pct}",
                "source: rule_first_learning",
                "---",
                "",
                "## Lesson Tags",
                *[f"- {tag}" for tag in metrics.lesson_tags],
                "",
                "## Codex Review",
                "Pending advisory review. Do not auto-apply config changes.",
                "",
            ]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.event_log.append_event(
            "learning.lesson_written",
            metrics.trade_id,
            {"path": str(path), "content_hash": content_hash(content), "tags": metrics.lesson_tags},
        )
        return path

    def write_advisory_proposal(self, metrics: LearningMetrics) -> Path:
        path = self.memory_root / "proposals" / f"PROPOSAL-{metrics.trade_id}.md"
        content = "\n".join(
            [
                "---",
                "status: pending_review",
                "proposed_by: rule_first_learning",
                f"trade_id: {metrics.trade_id}",
                f"symbol: {metrics.symbol}",
                "---",
                "",
                "## Proposal",
                "No automatic config change proposed in v1.",
                "",
                "## Evidence",
                f"- P&L INR: {metrics.pnl_inr}",
                f"- P&L pct: {metrics.pnl_pct}",
                "",
            ]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.event_log.append_event(
            "learning.proposal_written",
            metrics.trade_id,
            {"path": str(path), "content_hash": content_hash(content), "status": "pending_review"},
        )
        return path
