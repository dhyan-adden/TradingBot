"""Phase 2 (batch 2): live expected-position book and SELL dual-check."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradeloop.lib.broker.live_book import (
    load_live_expected_book,
    persist_live_expected_book,
)
from tradeloop.lib.broker.live_state import LiveBrokerSnapshot, compute_reconciliation
from tradeloop.lib.broker.paper_broker import OrderTicket


def _snap(holdings=None):
    return LiveBrokerSnapshot(
        checked_at=datetime.now(timezone.utc).isoformat(),
        auth_ok=True, holdings=holdings or {}, open_orders=[],
        available_cash_inr=1_000_000.0)


def test_missing_live_book_loads_empty(tmp_path):
    assert load_live_expected_book(tmp_path) == {}


def test_malformed_live_book_fails_closed(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "live_book.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_live_expected_book(tmp_path)


def test_sell_blocked_when_live_book_zero(tmp_path):
    status = compute_reconciliation(_snap(holdings={"RELIANCE": 5}),
                                    [OrderTicket("RELIANCE", "SELL", 1, 1000)],
                                    expected_book={})
    assert status.ok is False
    assert any("live-book" in r for r in status.reasons)


def test_sell_allowed_when_broker_and_live_book_sufficient(tmp_path):
    status = compute_reconciliation(_snap(holdings={"RELIANCE": 5}),
                                    [OrderTicket("RELIANCE", "SELL", 3, 1000)],
                                    expected_book={"RELIANCE": 5})
    assert status.ok is True


def test_sell_blocked_when_live_book_insufficient_but_broker_sufficient(tmp_path):
    status = compute_reconciliation(_snap(holdings={"RELIANCE": 10}),
                                    [OrderTicket("RELIANCE", "SELL", 6, 1000)],
                                    expected_book={"RELIANCE": 5})
    assert status.ok is False
    assert any("live-book" in r for r in status.reasons)


def test_buy_allowed_with_empty_live_book(tmp_path):
    status = compute_reconciliation(_snap(holdings={}),
                                    [OrderTicket("RELIANCE", "BUY", 1, 1000)],
                                    expected_book={})
    assert status.ok is True


def test_persist_roundtrip_normalizes_symbols_and_drops_zero(tmp_path):
    persist_live_expected_book(tmp_path, {"reliance": 2, "INFY": 0}, "zerodha_order_sync")
    assert load_live_expected_book(tmp_path) == {"RELIANCE": 2}
    data = json.loads((tmp_path / "state" / "live_book.json").read_text(encoding="utf-8"))
    assert data["source"] == "zerodha_order_sync"