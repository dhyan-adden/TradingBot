import json
from pathlib import Path

import pytest

from tradeloop.lib.broker.paper_book import append, hydrate
from tradeloop.lib.broker.paper_broker import OrderTicket, PaperBroker
from tradeloop.lib.broker.router import route_orders_file
from tradeloop.lib.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = load_settings(ROOT / "config" / "settings.yaml")


def _write(tmp_path: Path, of: dict) -> tuple[Path, Path]:
    orders = tmp_path / "orders.json"
    fills = tmp_path / "fills.json"
    orders.write_text(json.dumps(of), encoding="utf-8")
    return orders, fills


def _reasons(routed) -> list[str]:
    return list(routed.payload.get("reasons", []))


def test_rejects_non_universe_symbol(tmp_path: Path) -> None:
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "FAKECO", "side": "BUY", "quantity": 5, "price": 4000}]})
    routed = route_orders_file(orders, fills, PaperBroker(500000), SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "symbol_not_in_universe" in _reasons(routed[0])


def test_rejects_oversized_position(tmp_path: Path) -> None:
    # 100000 capital, 25% cap = 25000; 100 * 3000 = 300000 notional -> reject.
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "TCS", "side": "BUY", "quantity": 100, "price": 3000}]})
    routed = route_orders_file(orders, fills, PaperBroker(100000), SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "max_position_allocation_exceeded" in _reasons(routed[0])


def test_rejects_fifth_concurrent_position(tmp_path: Path) -> None:
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=10_000_000, slippage_bps=0)
    for sym, px in [("RELIANCE", 1000), ("TCS", 1000), ("HDFCBANK", 1000), ("INFY", 1000)]:
        fill = seed.place_order(OrderTicket(sym, "BUY", 1, px))
        append(book, [fill])
    broker = hydrate(book, starting_cash_inr=10_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "ICICIBANK", "side": "BUY", "quantity": 10, "price": 1000}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "max_open_positions_exceeded" in _reasons(routed[0])


def test_rejects_sell_exceeding_held(tmp_path: Path) -> None:
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=1_000_000, slippage_bps=0)
    fill = seed.place_order(OrderTicket("RELIANCE", "BUY", 3, 1000))
    append(book, [fill])
    broker = hydrate(book, starting_cash_inr=1_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "RELIANCE", "side": "SELL", "quantity": 10, "price": 1050}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT)
    assert routed[0].status == "RISK_REJECTED"
    assert "long_only_sell_exceeds_position" in _reasons(routed[0])


def test_hydrated_sell_within_held_fills(tmp_path: Path) -> None:
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=1_000_000, slippage_bps=0)
    fill = seed.place_order(OrderTicket("RELIANCE", "BUY", 5, 1000))
    append(book, [fill])
    broker = hydrate(book, starting_cash_inr=1_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "RELIANCE", "side": "SELL", "quantity": 2, "price": 1050}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT)
    assert routed[0].status == "FILLED"
    assert broker.positions == {"RELIANCE": 3}


def test_routes_orders_and_skips_held(tmp_path: Path) -> None:
    orders, fills = _write(tmp_path, {
        "orders": [{"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000}],
        "held": [{"ticker": "TCS", "side": "BUY", "quantity": 5, "price": 3000}],
    })
    routed = route_orders_file(orders, fills, PaperBroker(500000), SETTINGS, root=ROOT)
    assert len(routed) == 1  # held[] not routed
    written = json.loads(fills.read_text(encoding="utf-8"))
    assert len(written) == 1
    decisions = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(decisions) == 1


def test_postclose_blocks_all_orders(tmp_path: Path) -> None:
    # postclose = no trading: a proposed BUY must not route (regresses the 2026-07-07
    # bug where the mode-blind DAG proposed 3 postclose BUYs).
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000}]})
    routed = route_orders_file(orders, fills, PaperBroker(500000), SETTINGS, root=ROOT,
                               mode="postclose")
    assert routed[0].status == "MODE_DISALLOWED"
    written = json.loads(fills.read_text(encoding="utf-8"))
    assert written[0]["status"] == "MODE_DISALLOWED"


def test_intraday_blocks_new_buy_allows_sell_exit(tmp_path: Path) -> None:
    # intraday = manage existing longs only: new BUY entry blocked, SELL exit routes.
    book = tmp_path / "state" / "paper_book.jsonl"
    seed = PaperBroker(cash_inr=1_000_000, slippage_bps=0)
    append(book, [seed.place_order(OrderTicket("RELIANCE", "BUY", 5, 1000))])
    broker = hydrate(book, starting_cash_inr=1_000_000)
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "TCS", "side": "BUY", "quantity": 5, "price": 3000},
        {"ticker": "RELIANCE", "side": "SELL", "quantity": 2, "price": 1050}]})
    routed = route_orders_file(orders, fills, broker, SETTINGS, root=ROOT, mode="intraday")
    by_symbol = {r.payload.get("symbol"): r.status for r in routed}
    assert by_symbol["TCS"] == "MODE_DISALLOWED"
    assert by_symbol["RELIANCE"] == "FILLED"
    assert broker.positions == {"RELIANCE": 3}


def test_premarket_allows_new_buy(tmp_path: Path) -> None:
    # explicit mode="premarket" preserves the pre-gate happy path.
    orders, fills = _write(tmp_path, {"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000}]})
    routed = route_orders_file(orders, fills, PaperBroker(500000), SETTINGS, root=ROOT,
                               mode="premarket")
    assert routed[0].status == "FILLED"


def test_malformed_orders_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "orders.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception):
        route_orders_file(bad, tmp_path / "fills.json", PaperBroker(100000), SETTINGS, root=ROOT)


def test_sell_exempt_from_position_allocation_cap():
    from tradeloop.lib.risk.checks import RiskCaps, RiskState, evaluate

    state = RiskState(cash_inr=10000.0, positions={"CDSL": 100},
                      avg_prices={"CDSL": 1000.0}, sectors={})
    caps = RiskCaps(capital_inr=200000.0, max_open_positions=6,
                    max_position_allocation_pct=25.0, max_total_deployed_pct=80.0,
                    max_sector_allocation_pct=50.0, max_daily_drawdown_pct=3.0,
                    universe=["CDSL"])
    # position doubled: exit notional 150000 = 75% of capital, far over the 25% entry cap
    ticket = OrderTicket(symbol="CDSL", side="SELL", quantity=100, price=1500.0)
    verdict = evaluate(ticket, state, caps)
    assert verdict.approved, verdict.reasons
