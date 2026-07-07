import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from tradingbot.broker.paper import PaperBroker
from tradingbot.agents.schemas import PortfolioDecision, render_portfolio_decision
from tradingbot.event_log import Event, EventLog


@dataclass(frozen=True)
class ProjectionResult:
    path: Path
    changed: bool
    dry_run: bool


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class MemoryProjector:
    def __init__(self, event_log: EventLog, memory_root: Path):
        self.event_log = event_log
        self.memory_root = memory_root

    def regenerate_daily(self, dry_run: bool = False) -> List[ProjectionResult]:
        events = [
            event
            for event in self.event_log.replay()
            if not event.event_type.startswith("memory.")
        ]
        by_day: Dict[str, List[Event]] = {}
        for event in events:
            day = event.created_at[:10]
            by_day.setdefault(day, []).append(event)

        results: List[ProjectionResult] = []
        for day, day_events in by_day.items():
            path = self.memory_root / "daily" / f"{day}.md"
            content = self._daily_content(day, day_events)
            results.append(self._write_projection(path, content, dry_run))
            if not dry_run:
                self.event_log.append_event(
                    "memory.daily_written",
                    f"DAILY-{day}",
                    {"path": str(path), "content_hash": content_hash(content), "events": len(day_events)},
                )
        return results

    def regenerate_scorecard(self, broker: PaperBroker, dry_run: bool = False) -> ProjectionResult:
        portfolio = broker.portfolio()
        path = self.memory_root / "scorecards" / "paper_portfolio.md"
        content = "\n".join(
            [
                "---",
                "strategy: paper_portfolio",
                f"cash_inr: {portfolio.cash_inr}",
                f"open_positions: {len(portfolio.positions)}",
                f"realized_pnl_inr: {portfolio.realized_pnl_inr}",
                "---",
                "",
                "## Open Positions",
                *[
                    f"- {symbol}: quantity={quantity}, avg_price={portfolio.avg_prices.get(symbol, 0)}"
                    for symbol, quantity in sorted(portfolio.positions.items())
                ],
                "",
            ]
        )
        result = self._write_projection(path, content, dry_run)
        if not dry_run:
            self.event_log.append_event(
                "memory.scorecard_written",
                "SCORECARD-paper_portfolio",
                {"path": str(path), "content_hash": content_hash(content)},
            )
        return result

    def write_lesson_stub(self, aggregate_id: str, dry_run: bool = False) -> ProjectionResult:
        source_events = list(self.event_log.replay(aggregate_id))
        source_hash = content_hash("".join(event.event_hash for event in source_events))
        path = self.memory_root / "lessons" / f"LESSON-{aggregate_id}.md"
        content = "\n".join(
            [
                "---",
                f"source_aggregate_id: {aggregate_id}",
                f"source_event_hash: {source_hash}",
                "status: generated",
                "agent: codex_advisory_stub",
                "---",
                "",
                "## Lesson",
                "No closed-trade lesson is available yet. Review after the position is closed.",
                "",
                "## Evidence",
                *[f"- {event.event_type}: `{event.event_hash[:12]}`" for event in source_events],
                "",
            ]
        )
        result = self._write_projection(path, content, dry_run)
        if not dry_run:
            self.event_log.append_event(
                "memory.lesson_written",
                aggregate_id,
                {"path": str(path), "content_hash": content_hash(content), "source_event_hash": source_hash},
            )
        return result

    def write_portfolio_decision(
        self,
        decision: PortfolioDecision,
        aggregate_id: str,
        dry_run: bool = False,
    ) -> ProjectionResult:
        path = self.memory_root / "decisions" / f"{aggregate_id}.md"
        content = render_portfolio_decision(decision)
        result = self._write_projection(path, content, dry_run)
        if not dry_run:
            self.event_log.append_event(
                "memory.decision_written",
                aggregate_id,
                {"path": str(path), "content_hash": content_hash(content), "symbol": decision.symbol},
            )
        return result

    def _daily_content(self, day: str, events: Iterable[Event]) -> str:
        event_list = list(events)
        source_hash = content_hash("".join(event.event_hash for event in event_list))
        lines = [
            "---",
            f"date: {day}",
            f"source_event_hash: {source_hash}",
            f"event_count: {len(event_list)}",
            "---",
            "",
            "## Event Summary",
        ]
        for event in event_list:
            lines.append(
                f"- {event.created_at} {event.event_type} {event.aggregate_id} `{event.event_hash[:12]}`"
            )
        lines.append("")
        return "\n".join(lines)

    def _write_projection(self, path: Path, content: str, dry_run: bool) -> ProjectionResult:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        changed = existing != content
        if dry_run or not changed:
            return ProjectionResult(path=path, changed=changed, dry_run=dry_run)

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return ProjectionResult(path=path, changed=True, dry_run=False)
