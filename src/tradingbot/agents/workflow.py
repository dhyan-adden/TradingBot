from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.data.market import MarketDataAdapter
from tradingbot.event_log import EventLog
from tradingbot.memory.projections import MemoryProjector
from tradingbot.risk.engine import RiskEngine


@dataclass
class TradingState:
    symbol: str
    quantity: int
    strategy: str
    quote: Optional[Dict[str, Any]] = None
    risk_reasons: Optional[List[str]] = None
    order_id: Optional[str] = None
    memory_paths: Optional[List[str]] = None


class PaperTradingWorkflow:
    def __init__(
        self,
        market_data: MarketDataAdapter,
        risk_engine: RiskEngine,
        broker: PaperBroker,
        projector: MemoryProjector,
        event_log: EventLog,
    ):
        self.market_data = market_data
        self.risk_engine = risk_engine
        self.broker = broker
        self.projector = projector
        self.event_log = event_log

    def run_once(
        self,
        symbol: str,
        quantity: int,
        strategy: str = "paper_poll",
        side: Optional[str] = None,
    ) -> TradingState:
        state = TradingState(symbol=symbol.upper(), quantity=quantity, strategy=strategy)
        quote = self.market_data.quote(state.symbol)
        state.quote = {
            "symbol": quote.symbol,
            "source_symbol": quote.source_symbol,
            "last_price": quote.last_price,
            "timestamp": quote.timestamp,
            "source": quote.source,
        }
        self.event_log.append_event("market.quote_received", f"QUOTE-{state.symbol}", state.quote)

        if side:
            request = PaperOrderRequest(
                symbol=state.symbol,
                side=side,
                quantity=state.quantity,
                price=quote.last_price,
                strategy=strategy,
                source=quote.source,
            )
            decision = self.risk_engine.evaluate(request, self.broker.portfolio())
            state.risk_reasons = decision.reasons
            risk_event = "risk.approved" if decision.approved else "risk.rejected"
            self.event_log.append_event(
                risk_event,
                f"RISK-{state.symbol}",
                {"symbol": state.symbol, "approved": decision.approved, "reasons": decision.reasons},
            )
            if decision.approved:
                order_event = self.broker.place_order(request)
                state.order_id = order_event.aggregate_id
        else:
            state.risk_reasons = []
            self.event_log.append_event(
                "agent.decision.no_trade",
                f"DECISION-{state.symbol}",
                {"symbol": state.symbol, "strategy": strategy, "reason": "signals_not_enabled"},
            )

        self.broker.mark_to_market(state.symbol, quote.last_price, quote.source)
        daily = self.projector.regenerate_daily()
        scorecard = self.projector.regenerate_scorecard(self.broker)
        state.memory_paths = [str(item.path) for item in daily] + [str(scorecard.path)]
        return state
