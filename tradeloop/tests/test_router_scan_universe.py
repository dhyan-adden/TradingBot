"""Regression (bug 3): with universe.source=full_nse the analysts propose names
from the whole NSE scan, but the route gate only accepted the 6 hand-listed
config/universe.yaml symbols - so every scanned name (CDSL, DLF, ...) was blocked
at route as symbol_not_in_universe and could never fill.

Decision: trust the run's scan. The eligible route universe = tickers actually
scanned this cycle (<run>/full_scan.jsonl), plus the config base and current
holdings (a held name must always be exitable). Unknown names stay blocked.
"""
import json
from pathlib import Path

from tradeloop.lib.broker.paper_broker import PaperBroker
from tradeloop.lib.broker.router import route_orders_file
from tradeloop.lib.config import load_settings

ROOT = Path("tradeloop")


def _run_dir(tmp_path, scanned_tickers):
    (tmp_path / "full_scan.jsonl").write_text(
        "\n".join(json.dumps({"ticker": t, "setup_type": "20d_breakout"}) for t in scanned_tickers))
    return tmp_path


def _orders(run_dir, ticker, side, qty, price):
    p = run_dir / "orders.json"
    p.write_text(json.dumps({"mode": "premarket", "live_orders_enabled": False,
                             "orders": [{"ticker": ticker, "side": side, "product": "CNC",
                                         "quantity": qty, "price": price, "order_type": "LIMIT"}],
                             "held": []}))
    return p


def _reasons(routed, symbol):
    for r in routed:
        if r.payload.get("symbol") == symbol:
            return r.payload.get("reasons", [])
    return None


def test_scanned_symbol_not_in_config_is_routable(tmp_path):
    # CDSL is not in the 6-symbol config list, but it WAS scanned this cycle.
    settings = load_settings(ROOT / "config" / "settings.yaml")
    run = _run_dir(tmp_path, ["LUMAXIND", "CDSL", "DLF"])
    orders = _orders(run, "CDSL", "BUY", 20, 1000.0)   # 20k: within size/deploy caps
    book = PaperBroker(cash_inr=100000.0)

    routed = route_orders_file(orders, run / "fills.json", book, settings,
                               root=ROOT, mode="premarket")

    assert "CDSL" in book.positions                     # routed+filled, not rejected
    assert _reasons(routed, "CDSL") in (None, [])


def test_held_symbol_can_be_exited_even_if_unscanned(tmp_path):
    # A position must always be exitable, even if today's scan does not list it.
    settings = load_settings(ROOT / "config" / "settings.yaml")
    run = _run_dir(tmp_path, ["LUMAXIND"])              # CDSL NOT in scan
    orders = _orders(run, "CDSL", "SELL", 10, 1050.0)
    book = PaperBroker(cash_inr=50000.0, positions={"CDSL": 10}, avg_prices={"CDSL": 1000.0})

    routed = route_orders_file(orders, run / "fills.json", book, settings,
                               root=ROOT, mode="premarket")

    assert book.positions.get("CDSL", 0) == 0           # exited
    assert "symbol_not_in_universe" not in (_reasons(routed, "CDSL") or [])


def test_unknown_symbol_still_blocked(tmp_path):
    # Not scanned, not config, not held -> the gate must still reject it.
    settings = load_settings(ROOT / "config" / "settings.yaml")
    run = _run_dir(tmp_path, ["CDSL", "DLF"])
    orders = _orders(run, "NOTAREALTICKER", "BUY", 20, 1000.0)
    book = PaperBroker(cash_inr=100000.0)

    routed = route_orders_file(orders, run / "fills.json", book, settings,
                               root=ROOT, mode="premarket")

    assert "NOTAREALTICKER" not in book.positions
    assert "symbol_not_in_universe" in (_reasons(routed, "NOTAREALTICKER") or [])
