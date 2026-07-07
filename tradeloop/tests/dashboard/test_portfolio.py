from pathlib import Path

from tradeloop.dashboard.portfolio import portfolio_view
from tradeloop.dashboard.server import handle_api
from tradeloop.lib.broker.cost_model import estimate_cost
from tradeloop.lib.broker.paper_book import append as append_book
from tradeloop.lib.broker.paper_broker import Fill

START = 100000.0


def _seed_ledger(path: Path) -> None:
    append_book(path, [
        Fill("PAPER-1", "HDFCBANK", "BUY", 30, 830.62, "FILLED", "CNC"),
        Fill("PAPER-2", "SBIN", "BUY", 23, 1042.42, "FILLED", "CNC"),
    ], hard_stops={"HDFCBANK": 807.24, "SBIN": 1015.40})


def test_holdings_and_transactions_from_buys(tmp_path):
    db = tmp_path / "ledger.db"
    _seed_ledger(db)
    view = portfolio_view(db, START)

    assert [h["symbol"] for h in view["holdings"]] == ["HDFCBANK", "SBIN"]
    h = view["holdings"][0]
    assert h["quantity"] == 30 and h["avg_price"] == 830.62
    assert h["hard_stop"] == 807.24
    assert h["ltp"] is None and h["unrealized_pnl_inr"] is None  # no price_fn
    assert view["prices_live"] is False
    assert view["realized_pnl_inr"] == 0.0
    # transactions newest-first, dated, with costs
    assert len(view["transactions"]) == 2
    assert view["transactions"][0]["symbol"] == "SBIN"
    assert view["transactions"][0]["ts"]
    assert view["transactions"][0]["costs_inr"] > 0
    # cash mirrors the authoritative replay (start - notionals - costs)
    assert view["cash_inr"] < START - 30 * 830.62 - 23 * 1042.42 + 1


def test_sell_realizes_pnl_and_closes_position(tmp_path):
    db = tmp_path / "ledger.db"
    _seed_ledger(db)
    append_book(db, [Fill("PAPER-3", "SBIN", "SELL", 23, 1100.0, "FILLED", "CNC")])
    view = portfolio_view(db, START)

    assert [h["symbol"] for h in view["holdings"]] == ["HDFCBANK"]  # SBIN closed
    sell = view["transactions"][0]
    assert sell["side"] == "SELL" and sell["realized_pnl_inr"] is not None
    expected = (1100.0 * 23 - estimate_cost("SELL", "CNC", 23, 1100.0).total) - 1042.42 * 23
    assert abs(sell["realized_pnl_inr"] - expected) < 0.01
    assert abs(view["realized_pnl_inr"] - expected) < 0.01


def test_live_prices_mark_holdings(tmp_path):
    db = tmp_path / "ledger.db"
    _seed_ledger(db)
    view = portfolio_view(db, START, price_fn=lambda syms: {"HDFCBANK": 850.0, "SBIN": 1000.0})

    assert view["prices_live"] is True
    hdfc, sbin = view["holdings"]
    assert hdfc["unrealized_pnl_inr"] == round((850.0 - 830.62) * 30, 2)
    assert sbin["unrealized_pnl_inr"] == round((1000.0 - 1042.42) * 23, 2)  # a loss
    assert hdfc["stop_distance_pct"] == round((850.0 - 807.24) / 850.0 * 100, 2)
    assert view["equity_inr"] == round(view["cash_inr"] + view["market_value_inr"], 2)


def test_price_fn_failure_degrades_to_book_values(tmp_path):
    db = tmp_path / "ledger.db"
    _seed_ledger(db)

    def boom(_):
        raise RuntimeError("kite MCP closed stdout")

    view = portfolio_view(db, START, price_fn=boom)
    assert view["prices_live"] is False
    assert view["holdings"][0]["unrealized_pnl_inr"] is None
    assert view["market_value_inr"] > 0  # falls back to avg-price book value


def test_no_ledger_is_flat_book():
    view = portfolio_view(Path("/nonexistent/ledger.db"), START)
    assert view["equity_inr"] == START
    assert view["holdings"] == [] and view["transactions"] == []


def test_api_portfolio_route(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _seed_ledger(tmp_path / "state" / "ledger.db")
    status, body = handle_api("/api/portfolio", {}, runs_dir, price_fn=None)
    assert status == 200
    assert [h["symbol"] for h in body["holdings"]] == ["HDFCBANK", "SBIN"]
