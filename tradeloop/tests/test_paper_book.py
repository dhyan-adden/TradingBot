from pathlib import Path

from tradeloop.lib.broker.paper_book import append, hydrate
from tradeloop.lib.broker.paper_broker import OrderTicket, PaperBroker


def test_hydrate_replays_persisted_fills(tmp_path: Path) -> None:
    book = tmp_path / "paper_book.jsonl"
    broker = PaperBroker(cash_inr=100000, slippage_bps=0)
    buy = broker.place_order(OrderTicket("RELIANCE", "BUY", 10, 1000))
    append(book, [buy], hard_stops={"RELIANCE": 950.0})

    rehydrated = hydrate(book, starting_cash_inr=100000)
    assert rehydrated.positions == {"RELIANCE": 10}
    assert rehydrated.avg_prices["RELIANCE"] == 1000.0
    assert rehydrated.cash_inr == broker.cash_inr


def test_hydrated_sell_reduces_position(tmp_path: Path) -> None:
    book = tmp_path / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=100000, slippage_bps=0)
    buy = seed.place_order(OrderTicket("TCS", "BUY", 5, 3000))
    append(book, [buy], hard_stops={"TCS": 2900.0})

    broker = hydrate(book, starting_cash_inr=100000)
    sell = broker.place_order(OrderTicket("TCS", "SELL", 2, 3100))
    assert sell.status == "FILLED"
    assert broker.positions == {"TCS": 3}


def test_missing_book_starts_empty(tmp_path: Path) -> None:
    broker = hydrate(tmp_path / "nope.jsonl", starting_cash_inr=50000)
    assert broker.positions == {}
    assert broker.cash_inr == 50000
    assert broker.slippage_bps == 5  # restored for NEW orders (replay itself runs at 0)
