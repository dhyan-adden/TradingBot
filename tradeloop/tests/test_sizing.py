from tradeloop.lib.risk.sizing import apply_guardrails, atr_position_size, position_size_from_stop


def test_atr_sizing_and_guardrails() -> None:
    shares = atr_position_size(capital_inr=100000, entry_price=1000, atr_value=20, risk_per_trade_pct=1.5)
    assert shares == 37

    guarded = apply_guardrails(shares, entry_price=1000, equity_inr=100000, max_position_pct=25, adv20_inr=5000000)
    assert guarded == 25


def test_stop_based_sizing() -> None:
    shares = position_size_from_stop(100000, entry_price=1000, hard_stop=950, atr_value=20, per_trade_risk_pct=1.5)

    assert shares == 30

