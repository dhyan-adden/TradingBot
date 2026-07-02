from tradingbot.agents.indian_graph import build_indian_trading_graph, initial_indian_state


def test_indian_trading_graph_returns_hold_decision() -> None:
    graph = build_indian_trading_graph()

    result = graph.invoke(initial_indian_state("RELIANCE", "2026-05-16"))

    assert result["market_report"]["agent"] == "market_analyst"
    assert result["research_plan"]["recommendation"] == "Hold"
    assert result["trader_proposal"]["action"] == "Hold"
    assert result["portfolio_decision"]["rating"] == "Hold"
