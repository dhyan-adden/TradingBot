import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from tradingbot.agents.schemas import (
    AnalystReport,
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
)
from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.config import TradingConfig
from tradingbot.data.market import MarketDataAdapter
from tradingbot.event_log import EventLog
from tradingbot.learning import LearningProjector, closed_trade_metrics
from tradingbot.llm import ModelRouter
from tradingbot.memory.projections import MemoryProjector
from tradingbot.order_gate import OrderGate
from tradingbot.research import ResearchProvider, ResearchSummary, summarize_research
from tradingbot.risk.engine import RiskEngine
from tradingbot.runtime_log import log_step
from tradingbot.signals import simple_breakout_signal


@dataclass(frozen=True)
class AgentLoopResult:
    cycles: int
    symbols: List[str]
    research_items: int
    signals_generated: int
    vetoes: int
    orders_created: int
    dry_run: bool


class AgentLoopRunner:
    def __init__(
        self,
        config: TradingConfig,
        event_log: EventLog,
        market_data: MarketDataAdapter,
        research_provider: ResearchProvider,
        broker: PaperBroker,
        risk_engine: RiskEngine,
        memory_projector: MemoryProjector,
        order_gate: OrderGate | None = None,
        model_router: ModelRouter | None = None,
    ):
        self.config = config
        self.event_log = event_log
        self.market_data = market_data
        self.research_provider = research_provider
        self.broker = broker
        self.risk_engine = risk_engine
        self.memory_projector = memory_projector
        self.order_gate = order_gate
        self.model_router = model_router or ModelRouter(config.raw["agents"], event_log)
        self.learning_projector = LearningProjector(
            event_log,
            Path(config.raw["system"]["state"]["memory_root"]),
        )

    def run(self, symbols: List[str], cycles: int, poll_interval_seconds: int, dry_run: bool) -> AgentLoopResult:
        self.event_log.append_event(
            "agent_loop.started",
            "AGENT_LOOP",
            {"symbols": symbols, "cycles": cycles, "dry_run": dry_run},
        )
        log_step(self.event_log, "agent_loop", "started", symbols=symbols, cycles=cycles, dry_run=dry_run)
        research_count = 0
        signals = 0
        vetoes = 0
        orders = 0
        for cycle in range(cycles):
            self.event_log.append_event("agent_loop.heartbeat", "AGENT_LOOP", {"cycle": cycle + 1})
            log_step(self.event_log, "agent_loop", "cycle_started", cycle=cycle + 1, symbols=symbols)
            for symbol in symbols:
                outcome = self.run_symbol(symbol, dry_run=dry_run)
                research_count += outcome["research_items"]
                signals += 1
                vetoes += 1 if outcome["vetoed"] else 0
                orders += 1 if outcome["ordered"] else 0
            log_step(self.event_log, "memory", "regenerate_daily_started", cycle=cycle + 1)
            self.memory_projector.regenerate_daily()
            log_step(self.event_log, "memory", "regenerate_scorecard_started", cycle=cycle + 1)
            self.memory_projector.regenerate_scorecard(self.broker)
            log_step(self.event_log, "agent_loop", "cycle_completed", cycle=cycle + 1, signals=signals, vetoes=vetoes, orders=orders)
            if cycle + 1 < cycles and poll_interval_seconds > 0:
                time.sleep(poll_interval_seconds)
        return AgentLoopResult(cycles, symbols, research_count, signals, vetoes, orders, dry_run)

    def run_symbol(self, symbol: str, dry_run: bool) -> dict:
        normalized = symbol.upper()
        log_step(self.event_log, "symbol", "started", symbol=normalized, dry_run=dry_run)
        log_step(self.event_log, "researcher", "symbol_news_fetch_started", symbol=normalized)
        research_items = self.research_provider.fetch(normalized)
        log_step(self.event_log, "researcher", "symbol_news_fetch_completed", symbol=normalized, count=len(research_items))
        for item in research_items:
            self.event_log.append_event(
                "research.news_fetched",
                f"RESEARCH-{normalized}",
                item.__dict__,
            )
        research_summary = summarize_research(normalized, research_items)
        research_summary = self._model_research_summary(normalized, research_summary)
        log_step(self.event_log, "researcher", "summary_completed", symbol=normalized, sentiment=research_summary.sentiment)
        self.event_log.append_event(
            "research.trend_summary_written",
            f"RESEARCH-{normalized}",
            {
                "symbol": normalized,
                "summary": research_summary.summary,
                "sentiment": research_summary.sentiment,
                "sources": [item.url for item in research_summary.sources],
            },
        )

        log_step(self.event_log, "market_data", "quote_fetch_started", symbol=normalized)
        quote = self.market_data.quote(normalized)
        quote_payload = {
            "symbol": quote.symbol,
            "source_symbol": quote.source_symbol,
            "last_price": quote.last_price,
            "timestamp": quote.timestamp,
            "source": quote.source,
        }
        self.event_log.append_event("data.quote_received", f"QUOTE-{quote.symbol}", quote_payload)
        log_step(self.event_log, "market_data", "quote_fetch_completed", symbol=normalized, price=quote.last_price, source=quote.source)

        log_step(self.event_log, "agents", "analyst_reports_started", symbol=normalized)
        market_report = AnalystReport(
            agent="market_context_agent",
            symbol=normalized,
            summary=f"Last traded paper reference price is {quote.last_price} from {quote.source}.",
            evidence=[quote.source_symbol, quote.timestamp],
            confidence=0.6,
        )
        news_report = AnalystReport(
            agent="news_trend_agent",
            symbol=normalized,
            summary=research_summary.summary,
            evidence=[item.title for item in research_summary.sources[:5]],
            confidence=0.6 if research_items else 0.3,
        )
        market_report = self._model_analyst_report("market_analyst", market_report, {"quote": quote_payload})
        news_report = self._model_analyst_report(
            "news_analyst",
            news_report,
            {"headlines": [item.title for item in research_summary.sources[:10]], "sentiment": research_summary.sentiment},
        )
        self.event_log.append_event("agent.report_written", f"REPORT-{normalized}", market_report.model_dump(mode="json"))
        self.event_log.append_event("agent.report_written", f"REPORT-{normalized}", news_report.model_dump(mode="json"))
        log_step(self.event_log, "agents", "analyst_reports_completed", symbol=normalized)

        log_step(self.event_log, "trader", "proposal_started", symbol=normalized)
        trader = self._trader_proposal(normalized, research_summary, quote_payload)
        log_step(self.event_log, "portfolio_manager", "decision_started", symbol=normalized, trader_action=trader.action.value)
        portfolio_decision = self._portfolio_decision(normalized, research_summary, trader, quote_payload)
        self.event_log.append_event("agent.trader_proposal_written", f"TRADER-{normalized}", trader.model_dump(mode="json"))
        self.event_log.append_event(
            "agent.portfolio_decision_written",
            f"PORTFOLIO-{normalized}",
            portfolio_decision.model_dump(mode="json"),
        )
        log_step(
            self.event_log,
            "portfolio_manager",
            "decision_completed",
            symbol=normalized,
            allow_trade=portfolio_decision.allow_trade,
            rating=portfolio_decision.rating.value,
        )

        log_step(self.event_log, "signal", "generation_started", symbol=normalized)
        strategy = self._default_strategy()
        default_quantity = int(self.config.raw["paper_broker"].get("default_quantity", 1))
        signal = simple_breakout_signal(normalized, quote.last_price, self.broker.portfolio(), strategy, default_quantity)
        self.event_log.append_event(
            "signal.generated",
            f"SIGNAL-{normalized}",
            {
                "symbol": signal.symbol,
                "action": signal.action,
                "strategy": signal.strategy,
                "reason": signal.reason,
                "quantity": signal.quantity,
                "dry_run": dry_run,
            },
        )
        self._model_advisory(
            "signal_agent",
            "Review this deterministic signal. Return JSON with keys: summary, concerns, confidence.",
            {
                "symbol": signal.symbol,
                "action": signal.action,
                "reason": signal.reason,
                "strategy": signal.strategy,
                "quantity": signal.quantity,
                "quote": quote_payload,
            },
        )
        log_step(self.event_log, "signal", "generation_completed", symbol=normalized, action=signal.action, reason=signal.reason)
        log_step(self.event_log, "portfolio", "mark_to_market_started", symbol=normalized, price=quote.last_price)
        self.broker.mark_to_market(normalized, quote.last_price, quote.source)
        log_step(self.event_log, "portfolio", "mark_to_market_completed", symbol=normalized)

        if signal.action not in {"BUY", "SELL"}:
            self.event_log.append_event("signal.skipped", f"SIGNAL-{normalized}", {"symbol": normalized, "reason": signal.reason})
            log_step(self.event_log, "symbol", "completed_no_order", symbol=normalized, reason=signal.reason)
            return {"research_items": len(research_items), "vetoed": False, "ordered": False}

        if not portfolio_decision.allow_trade:
            self.event_log.append_event(
                "agent.vetoed",
                f"VETO-{normalized}",
                {"symbol": normalized, "reason": portfolio_decision.executive_summary, "signal_action": signal.action},
            )
            log_step(self.event_log, "portfolio_manager", "trade_vetoed", symbol=normalized, reason=portfolio_decision.executive_summary)
            return {"research_items": len(research_items), "vetoed": True, "ordered": False}

        request = PaperOrderRequest(
            symbol=normalized,
            side=signal.action,
            quantity=signal.quantity,
            price=quote.last_price,
            strategy=signal.strategy,
            source=quote.source,
        )
        log_step(self.event_log, "risk", "evaluation_started", symbol=normalized, side=request.side, quantity=request.quantity)
        risk = self.risk_engine.evaluate(request, self.broker.portfolio())
        self.event_log.append_event(
            "risk.approved" if risk.approved else "risk.rejected",
            f"RISK-{normalized}",
            {"symbol": normalized, "approved": risk.approved, "reasons": risk.reasons, "dry_run": dry_run},
        )
        self._model_advisory(
            "risk_agent",
            "Review this deterministic risk decision. Return JSON with keys: summary, concerns, confidence. Do not override the decision.",
            {
                "request": request.__dict__,
                "approved": risk.approved,
                "reasons": risk.reasons,
                "portfolio": self.broker.portfolio().__dict__,
            },
        )
        log_step(self.event_log, "risk", "evaluation_completed", symbol=normalized, approved=risk.approved, reasons=risk.reasons)
        if dry_run or not risk.approved:
            log_step(self.event_log, "symbol", "completed_without_broker", symbol=normalized, dry_run=dry_run, risk_approved=risk.approved)
            return {"research_items": len(research_items), "vetoed": False, "ordered": False}

        if self.order_gate is not None:
            self._model_advisory(
                "execution_agent",
                "Review this pending paper execution. Return JSON with keys: summary, concerns, confidence. Do not approve or place orders.",
                {"request": request.__dict__, "risk_reasons": risk.reasons},
            )
            log_step(self.event_log, "order_gate", "pending_started", symbol=normalized, side=request.side, quantity=request.quantity)
            gate_decision = self.order_gate.wait_for_decision(
                request,
                {
                    "symbol": normalized,
                    "signal_action": signal.action,
                    "strategy": signal.strategy,
                    "risk_reasons": risk.reasons,
                },
            )
            self.event_log.append_event(
                "execution.order_gate_decision",
                gate_decision.gate_id,
                {
                    "gate_id": gate_decision.gate_id,
                    "symbol": normalized,
                    "approved": gate_decision.approved,
                    "status": gate_decision.status,
                    "reason": gate_decision.reason,
                },
            )
            log_step(
                self.event_log,
                "order_gate",
                "decision_completed",
                symbol=normalized,
                approved=gate_decision.approved,
                status=gate_decision.status,
                reason=gate_decision.reason,
            )
            if not gate_decision.approved:
                log_step(self.event_log, "symbol", "completed_order_blocked", symbol=normalized, reason=gate_decision.reason)
                return {"research_items": len(research_items), "vetoed": False, "ordered": False}

        before = self.broker.portfolio()
        log_step(self.event_log, "broker", "paper_order_submit_started", symbol=normalized, side=request.side, quantity=request.quantity)
        order_event = self.broker.place_order(request)
        log_step(self.event_log, "broker", "paper_order_submit_completed", symbol=normalized, event_type=order_event.event_type, order_id=order_event.aggregate_id)
        if request.side == "SELL" and order_event.event_type == "paper.order.filled":
            log_step(self.event_log, "learning", "closed_trade_learning_started", symbol=normalized, order_id=order_event.aggregate_id)
            avg_price = before.avg_prices.get(normalized, request.price)
            metrics = closed_trade_metrics({**order_event.payload, "entry_price": avg_price})
            self.event_log.append_event("post_trade.metrics_written", metrics.trade_id, metrics.__dict__)
            self.learning_projector.write_rule_lesson(metrics)
            self.learning_projector.write_advisory_proposal(metrics)
            self._model_advisory(
                "post_trade_learning_agent",
                "Review this closed paper trade. Return JSON with keys: lesson, mistake_class, proposal, confidence.",
                metrics.__dict__,
            )
            log_step(self.event_log, "learning", "closed_trade_learning_completed", symbol=normalized, trade_id=metrics.trade_id)
        log_step(self.event_log, "symbol", "completed", symbol=normalized, ordered=order_event.event_type == "paper.order.filled")
        return {"research_items": len(research_items), "vetoed": False, "ordered": order_event.event_type == "paper.order.filled"}

    def _trader_proposal(self, symbol: str, research: ResearchSummary, quote_payload: dict) -> TraderProposal:
        if research.sentiment == "negative":
            fallback = TraderProposal(symbol=symbol, action=TraderAction.HOLD, reasoning="News trend is negative; wait for cleaner setup.")
        else:
            fallback = TraderProposal(symbol=symbol, action=TraderAction.BUY, reasoning="No news veto detected; allow signal engine to decide.", quantity=1)
        result = self.model_router.call_json(
            "trader_agent",
            (
                "Create a paper-trading trader proposal for this Indian equity. "
                "Return JSON with keys: action, reasoning, quantity. action must be Buy, Hold, or Sell.\n"
                f"Input: {self._json({'symbol': symbol, 'research': research.__dict__, 'quote': quote_payload, 'fallback': fallback.model_dump(mode='json')})}"
            ),
            fallback.model_dump(mode="json"),
        )
        return _coerce_trader_proposal(symbol, result.content, fallback)

    def _portfolio_decision(self, symbol: str, research: ResearchSummary, trader: TraderProposal, quote_payload: dict) -> PortfolioDecision:
        allow = trader.action == TraderAction.BUY and research.sentiment != "negative"
        rating = PortfolioRating.OVERWEIGHT if allow else PortfolioRating.HOLD
        fallback = PortfolioDecision(
            symbol=symbol,
            rating=rating,
            allow_trade=allow,
            executive_summary="Trade allowed for paper risk gate." if allow else "Trade vetoed by research context.",
            investment_thesis=research.summary,
            time_horizon="intraday paper validation cycle",
            risk_notes=["Paper-only", "Deterministic risk gate remains final authority"],
        )
        result = self.model_router.call_json(
            "portfolio_manager",
            (
                "Create a portfolio manager decision for this paper-trading proposal. "
                "Return JSON with keys: rating, allow_trade, executive_summary, investment_thesis, risk_notes. "
                "rating must be Buy, Overweight, Hold, Underweight, or Sell.\n"
                f"Input: {self._json({'symbol': symbol, 'research': research.__dict__, 'trader': trader.model_dump(mode='json'), 'quote': quote_payload, 'fallback': fallback.model_dump(mode='json')})}"
            ),
            fallback.model_dump(mode="json"),
        )
        decision = _coerce_portfolio_decision(symbol, result.content, fallback)
        if research.sentiment == "negative":
            return decision.model_copy(update={"allow_trade": False})
        return decision

    def _model_research_summary(self, symbol: str, fallback: ResearchSummary) -> ResearchSummary:
        result = self.model_router.call_json(
            "news_analyst",
            (
                "Summarize Indian equity headlines for the trading system. "
                "Return JSON with keys: summary, sentiment. sentiment must be positive, neutral, or negative.\n"
                f"Input: {self._json({'symbol': symbol, 'headlines': [item.title for item in fallback.sources[:10]], 'fallback': {'summary': fallback.summary, 'sentiment': fallback.sentiment}})}"
            ),
            {"summary": fallback.summary, "sentiment": fallback.sentiment},
        )
        sentiment = str(result.content.get("sentiment", fallback.sentiment)).lower()
        if sentiment not in {"positive", "neutral", "negative"}:
            sentiment = fallback.sentiment
        return ResearchSummary(
            symbol=symbol,
            summary=str(result.content.get("summary", fallback.summary)),
            sources=fallback.sources,
            sentiment=sentiment,
        )

    def _model_analyst_report(self, role: str, fallback: AnalystReport, context: dict) -> AnalystReport:
        result = self.model_router.call_json(
            role,
            (
                "Write a compact analyst report. Return JSON with keys: summary, evidence, confidence.\n"
                f"Input: {self._json({'fallback': fallback.model_dump(mode='json'), 'context': context})}"
            ),
            fallback.model_dump(mode="json"),
        )
        return AnalystReport(
            agent=fallback.agent,
            symbol=fallback.symbol,
            summary=str(result.content.get("summary", fallback.summary)),
            evidence=[str(item) for item in result.content.get("evidence", fallback.evidence)][:10],
            confidence=_coerce_confidence(result.content.get("confidence", fallback.confidence), fallback.confidence),
        )

    def _model_advisory(self, role: str, instruction: str, context: dict) -> None:
        result = self.model_router.call_json(
            role,
            f"{instruction}\nInput: {self._json(context)}",
            {"summary": "Model advisory unavailable; deterministic system controls remain final.", "confidence": 0},
        )
        self.event_log.append_event(
            "model.advisory_written",
            f"MODEL-{role.upper()}",
            {"role": role, "used_model": result.used_model, "reason": result.reason, "content": result.content},
        )

    def _json(self, payload: dict) -> str:
        return json_dumps_safe(payload)

    def _default_strategy(self) -> dict:
        strategies = self.config.raw["strategies"].get("strategies", [])
        for strategy in strategies:
            if strategy.get("enabled", False):
                return strategy
        return {"name": "daily_breakout_v1", "enabled": False}


def json_dumps_safe(payload: dict) -> str:
    import json

    return json.dumps(payload, default=str, ensure_ascii=True)


def _coerce_trader_proposal(symbol: str, content: dict, fallback: TraderProposal) -> TraderProposal:
    action = str(content.get("action", fallback.action.value)).strip()
    action_map = {"buy": TraderAction.BUY, "hold": TraderAction.HOLD, "sell": TraderAction.SELL}
    return TraderProposal(
        symbol=symbol,
        action=action_map.get(action.lower(), fallback.action),
        reasoning=str(content.get("reasoning", fallback.reasoning)),
        quantity=_coerce_int(content.get("quantity", fallback.quantity), fallback.quantity),
        entry_price=_coerce_float_or_none(content.get("entry_price", fallback.entry_price)),
        stop_loss=_coerce_float_or_none(content.get("stop_loss", fallback.stop_loss)),
        target_price=_coerce_float_or_none(content.get("target_price", fallback.target_price)),
        position_sizing=str(content["position_sizing"]) if content.get("position_sizing") else fallback.position_sizing,
    )


def _coerce_portfolio_decision(symbol: str, content: dict, fallback: PortfolioDecision) -> PortfolioDecision:
    rating = str(content.get("rating", fallback.rating.value)).strip()
    rating_map = {item.value.lower(): item for item in PortfolioRating}
    risk_notes = content.get("risk_notes", fallback.risk_notes)
    if not isinstance(risk_notes, list):
        risk_notes = fallback.risk_notes
    return PortfolioDecision(
        symbol=symbol,
        rating=rating_map.get(rating.lower(), fallback.rating),
        allow_trade=bool(content.get("allow_trade", fallback.allow_trade)),
        executive_summary=str(content.get("executive_summary", fallback.executive_summary)),
        investment_thesis=str(content.get("investment_thesis", fallback.investment_thesis)),
        price_target=_coerce_float_or_none(content.get("price_target", fallback.price_target)),
        time_horizon=str(content.get("time_horizon", fallback.time_horizon or "")) or fallback.time_horizon,
        risk_notes=[str(item) for item in risk_notes][:10],
    )


def _coerce_int(value: object, fallback: int | None) -> int | None:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_confidence(value: object, fallback: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return fallback
