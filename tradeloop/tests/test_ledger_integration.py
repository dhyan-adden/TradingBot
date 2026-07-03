from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger
from tradeloop.lib.audit.projections import MarkdownProjector
from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.paper_broker import Fill


def test_end_to_end_mixed_stream(tmp_path):
    db = tmp_path / "ledger.db"
    led = Ledger(db)
    led.log_fetch_ok("google_news", count=4)
    led.log_model_call("news", "m", prompt_tokens=100, completion_tokens=20, latency_ms=300)
    led.append({"type": "risk.verdict", "symbol": "TCS", "side": "BUY",
                "quantity": 10, "price": 100.0, "approved": True, "reasons": []})
    paper_book.append(db, [Fill("P1", "TCS", "BUY", 10, 100.0, "FILLED", "CNC")],
                      hard_stops={"TCS": 90.0})

    led.verify_chain()  # whole mixed chain intact

    broker = paper_book.hydrate(db, starting_cash_inr=1_000_000.0)
    assert broker.positions == {"TCS": 10}

    proj = MarkdownProjector(led, tmp_path / "memory")
    first = proj.regenerate_journal()
    assert first.changed is True
    assert proj.regenerate_journal().changed is False  # idempotent
