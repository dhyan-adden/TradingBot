"""Phase 7: live BUY canary cap - first live rollout is mechanically one-share only."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from tradeloop.lib.broker.paper_broker import OrderTicket, PaperBroker
from tradeloop.lib.broker.router import route_order
from tradeloop.lib.config import load_settings

_ROOT_SETTINGS = load_settings(
    Path(__file__).resolve().parents[1] / "config" / "settings.yaml")


def _canary_settings(max_quantity: int = 1):
    return dataclasses.replace(
        _ROOT_SETTINGS, live_canary_enabled=True, live_canary_max_quantity=max_quantity)


def test_paper_buy_quantity_20_still_fills():
    broker = PaperBroker(cash_inr=100000)
    routed = route_order(OrderTicket("RELIANCE", "BUY", 20, 1000), broker)
    assert routed.status == "FILLED"
    assert broker.positions.get("RELIANCE") == 20


def test_live_buy_quantity_20_blocked(monkeypatch):
    monkeypatch.setenv("ZERODHA_ENABLE_TRADING", "true")
    monkeypatch.setattr(
        "tradeloop.lib.broker.router.live_promotion_ready", lambda root, settings=None: True)
    routed = route_order(
        OrderTicket("RELIANCE", "BUY", 20, 1000), PaperBroker(100000),
        root=Path("/tmp"), settings=_canary_settings(1),
        live_route_authorized=True)
    assert routed.status == "LIVE_CANARY_BLOCKED"
    assert routed.payload["max_quantity"] == 1


def test_direct_live_buy_quantity_1_requires_route_context(monkeypatch):
    monkeypatch.setenv("ZERODHA_ENABLE_TRADING", "true")
    monkeypatch.setattr(
        "tradeloop.lib.broker.router.live_promotion_ready", lambda root, settings=None: True)
    routed = route_order(
        OrderTicket("RELIANCE", "BUY", 1, 1000), PaperBroker(100000),
        root=Path("/tmp"), settings=_canary_settings(1))
    assert routed.status == "LIVE_ROUTE_CONTEXT_REQUIRED"


def test_authorized_live_buy_quantity_1_proceeds(monkeypatch):
    monkeypatch.setenv("ZERODHA_ENABLE_TRADING", "true")
    monkeypatch.setattr(
        "tradeloop.lib.broker.router.live_promotion_ready", lambda root, settings=None: True)
    routed = route_order(
        OrderTicket("RELIANCE", "BUY", 1, 1000), PaperBroker(100000),
        root=Path("/tmp"), settings=_canary_settings(1),
        live_route_authorized=True)
    assert routed.status == "READY_FOR_CODEX_TOOL_CALL"


def test_live_sell_quantity_20_unchanged(monkeypatch):
    monkeypatch.setenv("ZERODHA_ENABLE_TRADING", "true")
    monkeypatch.setattr(
        "tradeloop.lib.broker.router.live_promotion_ready", lambda root, settings=None: True)
    routed = route_order(
        OrderTicket("RELIANCE", "SELL", 20, 1000), PaperBroker(100000),
        root=Path("/tmp"), settings=_canary_settings(1),
        live_route_authorized=True)
    # Canary guards BUY only; SELL is unaffected in this phase.
    assert routed.status == "READY_FOR_CODEX_TOOL_CALL"
