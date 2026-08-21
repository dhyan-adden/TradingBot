import json

from tradeloop.lib.broker.router import _resolve_market_price
from tradeloop.lib.broker.orders_schema import Order


def test_market_order_uses_captured_ltp(tmp_path):
    (tmp_path / "holdings_ltp.json").write_text(json.dumps({"ltps": {"CDSL": 1329.0}}))
    order = Order(ticker="CDSL", side="SELL", quantity=11, order_type="MARKET")
    resolved = _resolve_market_price(order, tmp_path)
    assert resolved.price == 1329.0
