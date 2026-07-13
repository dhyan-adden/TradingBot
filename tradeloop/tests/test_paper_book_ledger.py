
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


def test_append_stamps_plan_meta_on_fill_events(tmp_path):
    # Attribution scores each closed episode from its ENTRY fill, so the fill
    # event must carry the plan's target and strategy alongside the hard stop.
    from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger

    db = tmp_path / "ledger.db"
    fill = Fill(order_id="P1", symbol="TCS", side="BUY", quantity=10,
                fill_price=100.0, status="FILLED", product="CNC")
    paper_book.append(db, [fill], hard_stops={"TCS": 90.0},
                      plan_meta={"TCS": {"target_1": 120.0,
                                         "strategy_family": "breakout_20d_pullback"}})
    event = Ledger(db).replay([ORDER_FILLED])[0]
    assert event["hard_stop"] == 90.0
    assert event["target_1"] == 120.0
    assert event["strategy_family"] == "breakout_20d_pullback"


def test_append_skips_non_filled(tmp_path):
    db = tmp_path / "ledger.db"
    rejected = Fill(order_id="P2", symbol="TCS", side="BUY", quantity=10,
                    fill_price=0.0, status="REJECTED", product="CNC", reason="insufficient_cash")
    paper_book.append(db, [rejected])
    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {}
