from tradeloop.dashboard.render import render_stage, render_decision


def test_trade_plan_card_states_the_trade():
    raw = {"tickets": [{"ticker": "HDFCBANK", "side": "BUY", "quantity": 25,
                        "entry": 801.05, "hard_stop": 779.48, "target_1": 829.8,
                        "target_2": 844.2, "thesis": "Q1 breakout", "conviction": 7.0}]}
    view = render_stage("30_trade_plan", raw)
    p = " ".join(view.points)
    assert "HDFC Bank" in p and "25" in p and "801.05" in p and "779.48" in p


def test_risk_card_translates_decision():
    raw = {"decisions": [{"ticker": "HDFCBANK", "decision": "resize",
                         "resized_quantity": 14, "reasons": ["position cap"]}]}
    view = render_stage("40_risk_report", raw)
    p = " ".join(view.points)
    assert "HDFC Bank" in p and "14" in p and "resize" not in view.summary.lower()


def test_decision_card_buy():
    orders = {"orders": [{"ticker": "HDFCBANK", "side": "BUY", "quantity": 25,
                          "price": 801.05, "hard_stop": 779.48, "reason": "breakout"}], "held": []}
    view = render_decision(orders)
    assert "Proposing to BUY" in view.summary and "HDFC Bank" in view.summary


def test_decision_card_hold():
    view = render_decision({"orders": [], "held": []})
    assert "Holding" in view.summary
