from tradeloop.lib.broker.cost_model import estimate_cost


def test_cnc_buy_cost_includes_buy_side_stt_transaction_sebi_and_gst() -> None:
    cost = estimate_cost("BUY", "CNC", quantity=10, price=1000)

    assert cost.brokerage == 0
    assert cost.stt == 10
    assert cost.transaction == 0.31
    assert cost.sebi == 0.01
    assert cost.stamp == 1.5
    assert cost.gst == 0.06
    assert cost.dp == 0
    assert cost.total == 11.88


def test_cnc_sell_cost_includes_sell_side_stt_dp_transaction_sebi_and_gst() -> None:
    cost = estimate_cost("SELL", "CNC", quantity=10, price=1000)

    assert cost.stt == 10
    assert cost.transaction == 0.31
    assert cost.sebi == 0.01
    assert cost.gst == 0.06
    assert cost.dp == 15.34
    assert cost.total == 25.72


def test_mis_cost_includes_brokerage_cap() -> None:
    cost = estimate_cost("BUY", "MIS", quantity=100, price=1000)

    assert cost.brokerage == 20
    assert cost.stamp == 3
    assert cost.transaction == 3.07
    assert cost.sebi == 0.1
    assert cost.gst == 4.17
    assert cost.total == 30.34
