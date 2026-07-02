import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.config import TradingConfig
from tradingbot.data.market import MarketDataAdapter
from tradingbot.event_log import EventLog
from tradingbot.learning import LearningProjector, closed_trade_metrics
from tradingbot.memory.projections import MemoryProjector
from tradingbot.risk.engine import RiskEngine
from tradingbot.signals import SignalDecision, simple_breakout_signal


@dataclass(frozen=True)
class LoopResult:
    cycles: int
    symbols: List[str]
    orders_created: int
    signals_generated: int
    dry_run: bool


class ClosedLoopRunner:
    def __init__(
        self,
        config: TradingConfig,
        event_log: EventLog,
        market_data: MarketDataAdapter,
        broker: PaperBroker,
        risk_engine: RiskEngine,
        memory_projector: MemoryProjector,
    ):
        self.config = config
        self.event_log = event_log
        self.market_data = market_data
        self.broker = broker
        self.risk_engine = risk_engine
        self.memory_projector = memory_projector
        self.learning_projector = LearningProjector(
            event_log,
            Path(config.raw["system"]["state"]["memory_root"]),
        )

    def run(
        self,
        symbols: List[str],
        cycles: int,
        poll_interval_seconds: int,
        dry_run: bool,
    ) -> LoopResult:
        self.event_log.append_event(
            "loop.started",
            "LOOP",
            {"symbols": symbols, "cycles": cycles, "dry_run": dry_run},
        )
        orders = 0
        signals = 0
        for cycle in range(cycles):
            self.event_log.append_event("loop.heartbeat", "LOOP", {"cycle": cycle + 1})
            for symbol in symbols:
                signal = self.run_symbol(symbol, dry_run=dry_run)
                signals += 1
                if signal.action in {"BUY", "SELL"} and not dry_run:
                    orders += 1
            self.memory_projector.regenerate_daily()
            self.memory_projector.regenerate_scorecard(self.broker)
            if cycle + 1 < cycles and poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)
        return LoopResult(cycles=cycles, symbols=symbols, orders_created=orders, signals_generated=signals, dry_run=dry_run)

    def run_symbol(self, symbol: str, dry_run: bool) -> SignalDecision:
        quote = self.market_data.quote(symbol)
        quote_payload = {
            "symbol": quote.symbol,
            "source_symbol": quote.source_symbol,
            "last_price": quote.last_price,
            "timestamp": quote.timestamp,
            "source": quote.source,
        }
        self.event_log.append_event("data.quote_received", f"QUOTE-{quote.symbol}", quote_payload)

        strategy = self._default_strategy()
        default_quantity = int(self.config.raw["paper_broker"].get("default_quantity", 1))
        signal = simple_breakout_signal(
            quote.symbol,
            quote.last_price,
            self.broker.portfolio(),
            strategy,
            default_quantity,
        )
        self.event_log.append_event(
            "signal.generated",
            f"SIGNAL-{quote.symbol}",
            {
                "symbol": signal.symbol,
                "action": signal.action,
                "strategy": signal.strategy,
                "reason": signal.reason,
                "quantity": signal.quantity,
                "stop_loss": signal.stop_loss,
                "target_price": signal.target_price,
                "dry_run": dry_run,
            },
        )

        self.broker.mark_to_market(quote.symbol, quote.last_price, quote.source)
        if signal.action not in {"BUY", "SELL"}:
            self.event_log.append_event("signal.skipped", f"SIGNAL-{quote.symbol}", {"reason": signal.reason, "symbol": signal.symbol})
            return signal

        request = PaperOrderRequest(
            symbol=signal.symbol,
            side=signal.action,
            quantity=signal.quantity,
            price=quote.last_price,
            strategy=signal.strategy,
            source=quote.source,
        )
        decision = self.risk_engine.evaluate(request, self.broker.portfolio())
        self.event_log.append_event(
            "risk.approved" if decision.approved else "risk.rejected",
            f"RISK-{signal.symbol}",
            {"symbol": signal.symbol, "approved": decision.approved, "reasons": decision.reasons, "dry_run": dry_run},
        )
        if dry_run or not decision.approved:
            return signal

        before = self.broker.portfolio()
        order_event = self.broker.place_order(request)
        if request.side == "SELL" and order_event.event_type == "paper.order.filled":
            avg_price = before.avg_prices.get(signal.symbol, request.price)
            metrics = closed_trade_metrics({**order_event.payload, "entry_price": avg_price})
            self.event_log.append_event("learning.metrics_written", metrics.trade_id, metrics.__dict__)
            self.learning_projector.write_rule_lesson(metrics)
            self.learning_projector.write_advisory_proposal(metrics)
        return signal

    def _default_strategy(self) -> dict:
        strategies = self.config.raw["strategies"].get("strategies", [])
        for strategy in strategies:
            if strategy.get("enabled", False):
                return strategy
        return {"name": "daily_breakout_v1", "enabled": False}
