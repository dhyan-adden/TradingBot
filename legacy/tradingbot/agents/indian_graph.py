from datetime import date
from typing import Any, Dict
from typing_extensions import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from tradingbot.agents.schemas import (
    AnalystReport,
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
    TradingAgentsState,
)


class IndianGraphState(TypedDict):
    symbol: str
    trade_date: str
    market_report: NotRequired[Dict[str, Any]]
    news_report: NotRequired[Dict[str, Any]]
    fundamentals_report: NotRequired[Dict[str, Any]]
    sentiment_report: NotRequired[Dict[str, Any]]
    investment_debate: NotRequired[Dict[str, Any]]
    risk_debate: NotRequired[Dict[str, Any]]
    research_plan: NotRequired[Dict[str, Any]]
    trader_proposal: NotRequired[Dict[str, Any]]
    portfolio_decision: NotRequired[Dict[str, Any]]
    memory_context: NotRequired[str]
    metadata: NotRequired[Dict[str, str]]


def _state_from_dict(state: IndianGraphState) -> TradingAgentsState:
    return TradingAgentsState.model_validate(state)


def market_analyst_node(state: IndianGraphState) -> Dict[str, Any]:
    current = _state_from_dict(state)
    report = AnalystReport(
        agent="market_analyst",
        symbol=current.symbol,
        summary="Market analyst placeholder: technical signal generation is not enabled yet.",
        evidence=["paper harness active", "signals_not_enabled"],
        confidence=0.5,
    )
    return {"market_report": report.model_dump(mode="json")}


def research_manager_node(state: IndianGraphState) -> Dict[str, Any]:
    current = _state_from_dict(state)
    plan = ResearchPlan(
        symbol=current.symbol,
        recommendation=PortfolioRating.HOLD,
        rationale="Hold until the Indian-market signal layer and memory loop have more evidence.",
        strategic_actions="Continue paper polling, mark positions, and avoid automatic entries.",
    )
    return {"research_plan": plan.model_dump(mode="json")}


def trader_node(state: IndianGraphState) -> Dict[str, Any]:
    current = _state_from_dict(state)
    proposal = TraderProposal(
        symbol=current.symbol,
        action=TraderAction.HOLD,
        reasoning="No executable signal is available; paper execution should remain idle.",
    )
    return {"trader_proposal": proposal.model_dump(mode="json")}


def portfolio_manager_node(state: IndianGraphState) -> Dict[str, Any]:
    current = _state_from_dict(state)
    decision = PortfolioDecision(
        symbol=current.symbol,
        rating=PortfolioRating.HOLD,
        executive_summary="Maintain paper-only observation mode.",
        investment_thesis=(
            "The current system is validating Indian-market data, event logging, "
            "risk checks, and markdown memory before strategy automation."
        ),
        time_horizon="paper harness validation week",
        risk_notes=["No live execution", "No automatic entries without signal approval"],
    )
    return {"portfolio_decision": decision.model_dump(mode="json")}


def build_indian_trading_graph():
    workflow = StateGraph(IndianGraphState)
    workflow.add_node("Market Analyst", market_analyst_node)
    workflow.add_node("Research Manager", research_manager_node)
    workflow.add_node("Trader", trader_node)
    workflow.add_node("Portfolio Manager", portfolio_manager_node)
    workflow.add_edge(START, "Market Analyst")
    workflow.add_edge("Market Analyst", "Research Manager")
    workflow.add_edge("Research Manager", "Trader")
    workflow.add_edge("Trader", "Portfolio Manager")
    workflow.add_edge("Portfolio Manager", END)
    return workflow.compile()


def initial_indian_state(symbol: str, trade_date: str | None = None) -> Dict[str, Any]:
    return TradingAgentsState(
        symbol=symbol.strip().upper(),
        trade_date=trade_date or date.today().isoformat(),
    ).model_dump(mode="json")
