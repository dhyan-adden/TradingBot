"""Regression: the deterministic route gate must enforce PORTFOLIO-level caps
across a whole orders batch, not just per order against a pre-batch snapshot.

Two bugs this locks down (found while reviewing the 2026-07-10 claude run):
  1. route_orders_file built the RiskState once before the loop, so a second
     order in the same batch was checked against stale (pre-fill) deployment -
     two orders that each fit could together breach max_total_deployed_pct.
  2. _risk_state narrowed the sector map to symbols already in the book, so an
     incoming NEW symbol had no sector and the sector cap was silently skipped.

Symbols are real config/universe.yaml names (RELIANCE=Energy, TCS=IT,
HDFCBANK/ICICIBANK=Financial Services); order prices/qtys are chosen so the
notionals hit the caps regardless of live market price.
"""
import json
from pathlib import Path

from tradeloop.lib.broker.paper_broker import PaperBroker
from tradeloop.lib.broker.router import route_orders_file
from tradeloop.lib.config import load_settings

ROOT = Path("tradeloop")


def _orders(tmp_path, *legs):
    p = tmp_path / "orders.json"
    orders = [{"ticker": t, "side": "BUY", "product": "CNC",
               "quantity": q, "price": pr, "order_type": "LIMIT"} for t, q, pr in legs]
    p.write_text(json.dumps({"mode": "premarket", "live_orders_enabled": False,
                             "orders": orders, "held": []}))
    return p


def _blocked_reasons(routed):
    return {r.payload.get("symbol"): r.payload.get("reasons", [])
            for r in routed if r.status == "RISK_REJECTED"}


def test_batch_cannot_breach_total_deployed_cap(tmp_path):
    # equity 100k: RELIANCE 48k already deployed (48%), 52k cash. Two new orders
    # of 22.5k each: each alone -> ~70.5k (<90k cap), but both -> 93k (>90k).
    settings = load_settings(ROOT / "config" / "settings.yaml")
    book = PaperBroker(cash_inr=52000.0, positions={"RELIANCE": 48},
                       avg_prices={"RELIANCE": 1000.0})
    orders = _orders(tmp_path, ("TCS", 15, 1500.0), ("HDFCBANK", 15, 1500.0))

    routed = route_orders_file(orders, tmp_path / "fills.json", book, settings,
                               root=ROOT, mode="premarket")

    # first order fits and fills; the second must be blocked on the CUMULATIVE cap
    assert "TCS" in book.positions                       # order 1 routed
    assert "HDFCBANK" not in book.positions              # order 2 blocked, did NOT fill
    assert "max_total_deployed_exceeded" in _blocked_reasons(routed).get("HDFCBANK", [])


def test_new_symbol_counts_toward_sector_cap(tmp_path):
    # HDFCBANK 45k already deployed (Financial, 45%). A NEW Financial name
    # (ICICIBANK 16k) pushes the sector to 61% > 50% cap and must be blocked -
    # even though it is not yet in the book.
    settings = load_settings(ROOT / "config" / "settings.yaml")
    book = PaperBroker(cash_inr=55000.0, positions={"HDFCBANK": 45},
                       avg_prices={"HDFCBANK": 1000.0})
    orders = _orders(tmp_path, ("ICICIBANK", 16, 1000.0))

    routed = route_orders_file(orders, tmp_path / "fills.json", book, settings,
                               root=ROOT, mode="premarket")

    assert "ICICIBANK" not in book.positions             # blocked, did NOT fill
    assert "max_sector_allocation_exceeded" in _blocked_reasons(routed).get("ICICIBANK", [])
