from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PortfolioRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


class AnalystReport(BaseModel):
    agent: str
    symbol: str
    summary: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ResearchPlan(BaseModel):
    symbol: str
    recommendation: PortfolioRating
    rationale: str
    strategic_actions: str


class TraderProposal(BaseModel):
    symbol: str
    action: TraderAction
    reasoning: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    quantity: Optional[int] = None
    position_sizing: Optional[str] = None


class PortfolioDecision(BaseModel):
    symbol: str
    rating: PortfolioRating
    allow_trade: bool = False
    executive_summary: str
    investment_thesis: str
    price_target: Optional[float] = None
    time_horizon: Optional[str] = None
    risk_notes: List[str] = Field(default_factory=list)


class DebateState(BaseModel):
    history: str = ""
    current_response: str = ""
    count: int = 0


class TradingAgentsState(BaseModel):
    symbol: str
    trade_date: str
    market_report: Optional[AnalystReport] = None
    news_report: Optional[AnalystReport] = None
    fundamentals_report: Optional[AnalystReport] = None
    sentiment_report: Optional[AnalystReport] = None
    investment_debate: DebateState = Field(default_factory=DebateState)
    risk_debate: DebateState = Field(default_factory=DebateState)
    research_plan: Optional[ResearchPlan] = None
    trader_proposal: Optional[TraderProposal] = None
    portfolio_decision: Optional[PortfolioDecision] = None
    memory_context: str = ""
    metadata: Dict[str, str] = Field(default_factory=dict)


def render_portfolio_decision(decision: PortfolioDecision) -> str:
    parts = [
        "---",
        f"symbol: {decision.symbol}",
        f"rating: {decision.rating.value}",
        f"allow_trade: {str(decision.allow_trade).lower()}",
        "---",
        "",
        "## Executive Summary",
        decision.executive_summary,
        "",
        "## Investment Thesis",
        decision.investment_thesis,
    ]
    if decision.price_target is not None:
        parts.extend(["", "## Price Target", str(decision.price_target)])
    if decision.time_horizon:
        parts.extend(["", "## Time Horizon", decision.time_horizon])
    if decision.risk_notes:
        parts.extend(["", "## Risk Notes", *[f"- {note}" for note in decision.risk_notes]])
    return "\n".join(parts) + "\n"
