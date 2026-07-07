import time
from dataclasses import dataclass
from typing import List

from tradingbot.agent_loop import AgentLoopRunner
from tradingbot.event_log import EventLog
from tradingbot.market_clock import MarketClock
from tradingbot.research import ResearchProvider, ShortlistCandidate, scan_market_news
from tradingbot.runtime_log import log_step


@dataclass(frozen=True)
class AutonomousLoopResult:
    cycles: int
    shortlisted_symbols: List[str]
    research_items: int
    signals_generated: int
    vetoes: int
    orders_created: int
    dry_run: bool


class AutonomousLoopRunner:
    def __init__(
        self,
        event_log: EventLog,
        agent_runner: AgentLoopRunner,
        research_provider: ResearchProvider,
        universe: List[str],
        loop_config: dict,
    ):
        self.event_log = event_log
        self.agent_runner = agent_runner
        self.research_provider = research_provider
        self.universe = [symbol.upper() for symbol in universe]
        self.loop_config = loop_config
        self.market_clock = MarketClock(loop_config)

    def run(self, cycles: int, poll_interval_seconds: int, dry_run: bool) -> AutonomousLoopResult:
        self.event_log.append_event(
            "autonomous_loop.started",
            "AUTONOMOUS_LOOP",
            {"cycles": cycles, "dry_run": dry_run},
        )
        log_step(self.event_log, "autonomous", "started", cycles=cycles, dry_run=dry_run)
        latest_symbols: List[str] = []
        research_items = 0
        signals = 0
        vetoes = 0
        orders = 0
        for cycle in range(cycles):
            session = self.market_clock.session()
            cycle_dry_run = dry_run or not session.is_open
            self.event_log.append_event("autonomous_loop.heartbeat", "AUTONOMOUS_LOOP", {"cycle": cycle + 1})
            self.event_log.append_event(
                "market.session_checked",
                "MARKET_SESSION",
                {
                    "cycle": cycle + 1,
                    "is_open": session.is_open,
                    "phase": session.phase,
                    "reason": session.reason,
                    "local_time": session.local_time,
                    "timezone": session.timezone,
                    "execution_dry_run": cycle_dry_run,
                },
            )
            log_step(
                self.event_log,
                "autonomous",
                "cycle_started",
                cycle=cycle + 1,
                market_phase=session.phase,
                execution_dry_run=cycle_dry_run,
            )
            log_step(self.event_log, "researcher", "market_scan_started", cycle=cycle + 1, universe_size=len(self.universe))
            shortlist = self.shortlist()
            latest_symbols = [candidate.symbol for candidate in shortlist]
            self.event_log.append_event(
                "research.shortlist_generated",
                f"SHORTLIST-{cycle + 1}",
                {
                    "cycle": cycle + 1,
                    "symbols": latest_symbols,
                    "candidates": [candidate.__dict__ for candidate in shortlist],
                },
            )
            log_step(self.event_log, "researcher", "shortlist_generated", cycle=cycle + 1, symbols=latest_symbols)
            if latest_symbols:
                try:
                    log_step(self.event_log, "agent_loop", "shortlist_handoff", cycle=cycle + 1, symbols=latest_symbols, dry_run=cycle_dry_run)
                    result = self.agent_runner.run(
                        symbols=latest_symbols,
                        cycles=1,
                        poll_interval_seconds=0,
                        dry_run=cycle_dry_run,
                    )
                except Exception as exc:
                    self.event_log.append_event(
                        "autonomous_server.error",
                        "AUTONOMOUS_SERVER",
                        {"cycle": cycle + 1, "error": str(exc), "symbols": latest_symbols},
                    )
                    log_step(self.event_log, "autonomous", "cycle_error", cycle=cycle + 1, error=str(exc), symbols=latest_symbols)
                    result = None
                if result is None:
                    if cycle + 1 < cycles and poll_interval_seconds > 0:
                        time.sleep(poll_interval_seconds)
                    continue
                research_items += result.research_items
                signals += result.signals_generated
                vetoes += result.vetoes
                orders += result.orders_created
                log_step(
                    self.event_log,
                    "autonomous",
                    "cycle_completed",
                    cycle=cycle + 1,
                    research_items=result.research_items,
                    signals=result.signals_generated,
                    vetoes=result.vetoes,
                    orders=result.orders_created,
                    market_phase=session.phase,
                    execution_dry_run=cycle_dry_run,
                )
            if cycle + 1 < cycles and poll_interval_seconds > 0:
                log_step(self.event_log, "autonomous", "sleeping", seconds=poll_interval_seconds)
                time.sleep(poll_interval_seconds)
        log_step(self.event_log, "autonomous", "finished", cycles=cycles, orders=orders, dry_run=dry_run)
        return AutonomousLoopResult(cycles, latest_symbols, research_items, signals, vetoes, orders, dry_run)

    def shortlist(self) -> List[ShortlistCandidate]:
        autonomous_config = self.loop_config.get("autonomous", {})
        max_shortlist = int(autonomous_config.get("max_shortlist", self.loop_config.get("max_symbols_per_cycle", 5)))
        query_text = str(autonomous_config.get("discovery_query", "NSE stocks India market today"))
        per_symbol_news_limit = int(autonomous_config.get("per_symbol_news_limit", 3))
        scan = getattr(self.research_provider, "scan_market", None)
        if callable(scan):
            return scan(
                candidate_symbols=self.universe,
                max_shortlist=max_shortlist,
                query_text=query_text,
                per_symbol_news_limit=per_symbol_news_limit,
            )
        return scan_market_news(
            provider=self.research_provider,
            candidate_symbols=self.universe,
            max_shortlist=max_shortlist,
            query_text=query_text,
            per_symbol_news_limit=per_symbol_news_limit,
        )
