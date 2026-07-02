from tradeloop.lib.broker.cost_model import estimate_cost


def test_cnc_cost_includes_sell_side_stt_and_dp() -> None:
    cost = estimate_cost("SELL", "CNC", quantity=10, price=1000)

    assert cost.stt == 10
    assert cost.dp == 15.93
    assert cost.total == 25.93


def test_mis_cost_includes_brokerage_cap() -> None:
    cost = estimate_cost("BUY", "MIS", quantity=100, price=1000)

    assert cost.brokerage == 20
    assert cost.stamp == 3
    assert cost.gst == 3.6
    assert cost.total == 26.6

