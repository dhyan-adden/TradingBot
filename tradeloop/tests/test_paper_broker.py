from tradeloop.lib.broker.paper_broker import OrderTicket, PaperBroker
from tradeloop.lib.broker.router import live_promotion_ready, route_order


def test_paper_broker_rejects_sell_without_existing_long_position() -> None:
    broker = PaperBroker(cash_inr=100000)

    fill = broker.place_order(OrderTicket(symbol="RELIANCE", side="SELL", quantity=1, price=2500))

    assert fill.status == "REJECTED"
    assert fill.reason == "long_only_sell_exceeds_position"
    assert broker.positions == {}


def test_paper_broker_allows_buy_and_long_exit_with_costs() -> None:
    broker = PaperBroker(cash_inr=100000, slippage_bps=0)

    buy = broker.place_order(OrderTicket(symbol="RELIANCE", side="BUY", quantity=2, price=1000))
    sell = broker.place_order(OrderTicket(symbol="RELIANCE", side="SELL", quantity=1, price=1100))

    assert buy.status == "FILLED"
    assert sell.status == "FILLED"
    assert broker.positions == {"RELIANCE": 1}
    assert broker.cash_inr < 99100


def test_router_blocks_when_kill_switch_exists(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    root.mkdir()
    (root / "kill_switch.md").write_text("halt", encoding="utf-8")
    routed = route_order(OrderTicket("RELIANCE", "BUY", 1, 1000), PaperBroker(100000), root=root)

    assert routed.status == "KILL_SWITCH_ACTIVE"


def test_live_promotion_gate_checks_thresholds(tmp_path) -> None:
    root = tmp_path / "tradeloop"
    memory = root / "memory"
    memory.mkdir(parents=True)
    (memory / "strategy_performance.md").write_text(
        "paper_trades: 40\nwin_rate: 0.45\nexpectancy_r: 0.3\nmax_drawdown_pct: 8\n",
        encoding="utf-8",
    )

    assert live_promotion_ready(root)
