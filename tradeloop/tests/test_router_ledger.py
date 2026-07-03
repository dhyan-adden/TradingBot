import json
from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger, RISK_VERDICT
from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.router import route_orders_file
from tradeloop.lib.config import load_settings

ROOT = Path("tradeloop")


def _orders(tmp_path: Path, symbol: str, qty: int, price: float) -> Path:
    p = tmp_path / "orders.json"
    p.write_text(json.dumps({
        "mode": "premarket",
        "live_orders_enabled": False,
        "orders": [{"ticker": symbol, "side": "BUY", "product": "CNC",
                    "quantity": qty, "price": price, "order_type": "LIMIT"}],
        "held": [],
    }))
    return p


def test_route_logs_a_risk_verdict_per_order(tmp_path):
    settings = load_settings(ROOT / "config" / "settings.yaml")
    db = tmp_path / "ledger.db"
    led = Ledger(db)
    book = paper_book.hydrate(db, starting_cash_inr=settings.paper_starting_inr)
    # pick a symbol guaranteed in config/universe.yaml (first configured symbol).
    # load_ticker_master returns List[TickerRecord] (P0); TickerMaster.symbols()
    # only exists in P3, so index the list and read .symbol here.
    from tradeloop.lib.data.ticker_master import load_ticker_master
    symbol = load_ticker_master(ROOT / "config" / "universe.yaml")[0].symbol
    orders = _orders(tmp_path, symbol, qty=1, price=100.0)  # tiny -> below_min_position_size -> rejected

    route_orders_file(orders, tmp_path / "fills.json", book, settings, root=ROOT, ledger=led)

    verdicts = led.replay([RISK_VERDICT])
    assert len(verdicts) == 1
    assert verdicts[0]["symbol"] == symbol.upper()
    assert verdicts[0]["approved"] is False
    assert "below_min_position_size" in verdicts[0]["reasons"]
    led.verify_chain()  # chain stays intact after logging
