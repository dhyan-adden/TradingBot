
from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.paper_broker import Fill, PaperBroker


def test_hydrate_empty_ledger_returns_starting_cash(tmp_path):
    broker = paper_book.hydrate(tmp_path / "ledger.db", starting_cash_inr=750_000.0)
    assert isinstance(broker, PaperBroker)
    assert broker.cash_inr == 750_000.0
    assert broker.positions == {}


def test_append_then_hydrate_roundtrips_position(tmp_path):
    db = tmp_path / "ledger.db"
    fill = Fill(order_id="P1", symbol="TCS", side="BUY", quantity=10,
                fill_price=100.0, status="FILLED", product="CNC")
    paper_book.append(db, [fill])
    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {"TCS": 10}
    assert broker.avg_prices["TCS"] == 100.0


def test_append_skips_non_filled(tmp_path):
    db = tmp_path / "ledger.db"
    rejected = Fill(order_id="P2", symbol="TCS", side="BUY", quantity=10,
                    fill_price=0.0, status="REJECTED", product="CNC", reason="insufficient_cash")
    paper_book.append(db, [rejected])
    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {}
