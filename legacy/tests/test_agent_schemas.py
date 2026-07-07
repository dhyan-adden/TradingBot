from pydantic import ValidationError
import pytest

from tradingbot.agents.schemas import (
    AnalystReport,
    PortfolioDecision,
    PortfolioRating,
    TraderAction,
    TraderProposal,
    TradingAgentsState,
    render_portfolio_decision,
)


def test_trading_agents_state_defaults_for_indian_symbol() -> None:
    state = TradingAgentsState(symbol="RELIANCE", trade_date="2026-05-16")

    assert state.symbol == "RELIANCE"
    assert state.investment_debate.count == 0
    assert state.risk_debate.history == ""
    assert state.metadata == {}


def test_analyst_report_validates_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        AnalystReport(agent="market_analyst", symbol="RELIANCE", summary="x", confidence=1.5)


def test_portfolio_decision_renders_markdown() -> None:
    decision = PortfolioDecision(
        symbol="RELIANCE",
        rating=PortfolioRating.BUY,
        allow_trade=True,
        executive_summary="Paper buy candidate with controlled risk.",
        investment_thesis="Momentum and risk budget support a small test trade.",
        price_target=1400,
        time_horizon="5 trading days",
        risk_notes=["Paper-only", "Respect kill switch"],
    )

    markdown = render_portfolio_decision(decision)

    assert "rating: Buy" in markdown
    assert "allow_trade: true" in markdown
    assert "## Executive Summary" in markdown
    assert "- Paper-only" in markdown


def test_trader_proposal_action_is_typed() -> None:
    proposal = TraderProposal(
        symbol="RELIANCE",
        action=TraderAction.HOLD,
        reasoning="Signals are not enabled yet.",
    )

    assert proposal.action == TraderAction.HOLD
