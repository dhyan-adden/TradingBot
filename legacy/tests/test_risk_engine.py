from tradingbot.broker.paper import PaperOrderRequest, PaperPortfolio
from tradingbot.risk.engine import RiskEngine, RiskLimits


def limits() -> RiskLimits:
    return RiskLimits(
        paper_capital_inr=100000,
        max_open_positions=1,
        max_position_allocation_pct=20,
        max_total_deployed_pct=60,
    )


def test_approves_valid_buy() -> None:
    engine = RiskEngine(limits(), ["RELIANCE"])
    portfolio = PaperPortfolio(cash_inr=100000, positions={}, avg_prices={}, realized_pnl_inr=0)

    decision = engine.evaluate(PaperOrderRequest("RELIANCE", "BUY", 1, 1000), portfolio)

    assert decision.approved is True
    assert decision.reasons == []


def test_rejects_symbol_outside_universe() -> None:
    engine = RiskEngine(limits(), ["RELIANCE"])
    portfolio = PaperPortfolio(cash_inr=100000, positions={}, avg_prices={}, realized_pnl_inr=0)

    decision = engine.evaluate(PaperOrderRequest("TCS", "BUY", 1, 1000), portfolio)

    assert decision.approved is False
    assert "symbol_not_in_universe" in decision.reasons


def test_rejects_active_kill_switch() -> None:
    engine = RiskEngine(limits(), ["RELIANCE"], kill_switch_active=True)
    portfolio = PaperPortfolio(cash_inr=100000, positions={}, avg_prices={}, realized_pnl_inr=0)

    decision = engine.evaluate(PaperOrderRequest("RELIANCE", "BUY", 1, 1000), portfolio)

    assert decision.approved is False
    assert "kill_switch_active" in decision.reasons
