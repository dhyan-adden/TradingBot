from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from tradeloop.lib.audit.attribution import StrategyPerformance, render_strategy_performance, report
from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.memory.dossier import update_dossier
from tradeloop.lib.memory.writer import append_provenanced


@dataclass(frozen=True)
class LearningResult:
    performance: StrategyPerformance
    journal_entries: int
    strategy_performance_path: Path


def run_postclose_learning(run_dir: Path, memory_root: Path, fills: List[dict],
                           run_id: str, timestamp: str, live_ready: bool = False) -> LearningResult:
    trade_plans = load_orders(run_dir / "orders.json")
    perf = report(trade_plans, fills)

    journal_path = memory_root / "trade_journal.md"
    entries = 0
    for ta in perf.trades:
        body = (
            f"strategy: {ta.strategy_family}\n"
            f"outcome: {ta.outcome.value}\n"
            f"expected_r: {ta.expected_r}\n"
            f"realized_r: {ta.realized_r}"
        )
        heading = f"{ta.symbol} {timestamp}"
        if append_provenanced(journal_path, heading, body, run_id=run_id, timestamp=timestamp):
            entries += 1
        update_dossier(memory_root, ta.symbol,
                       heading=f"{timestamp} outcome",
                       body=f"realized_r {ta.realized_r} ({ta.outcome.value}) via {ta.strategy_family}")

    perf_path = memory_root / "strategy_performance.md"
    perf_path.parent.mkdir(parents=True, exist_ok=True)
    perf_path.write_text(render_strategy_performance(perf, live_ready=live_ready), encoding="utf-8")

    return LearningResult(performance=perf, journal_entries=entries, strategy_performance_path=perf_path)
