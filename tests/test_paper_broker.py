from pathlib import Path

from tradingbot.broker.paper import PaperBroker, PaperOrderRequest
from tradingbot.event_log import EventLog


def test_buy_and_sell_updates_paper_portfolio(tmp_path: Path) -> None:
    broker = PaperBroker(EventLog(tmp_path / "trading.db"), starting_cash_inr=1000)

    buy = broker.place_order(PaperOrderRequest("RELIANCE", "BUY", 2, 100))
    sell = broker.place_order(PaperOrderRequest("RELIANCE", "SELL", 1, 125))
    portfolio = broker.portfolio()

    assert buy.event_type == "paper.order.filled"
    assert sell.event_type == "paper.order.filled"
    assert portfolio.cash_inr == 925
    assert portfolio.positions == {"RELIANCE": 1}
    assert portfolio.realized_pnl_inr == 25


def test_rejects_insufficient_cash(tmp_path: Path) -> None:
    broker = PaperBroker(EventLog(tmp_path / "trading.db"), starting_cash_inr=100)

    event = broker.place_order(PaperOrderRequest("RELIANCE", "BUY", 2, 100))

    assert event.event_type == "paper.order.rejected"
    assert event.payload["reason"] == "insufficient_cash"
