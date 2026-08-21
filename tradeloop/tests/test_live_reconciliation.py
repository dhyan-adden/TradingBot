"""Phase 9: live route requires Zerodha account state to match TradeLoop state."""
from __future__ import annotations

import dataclasses
import json
import subprocess
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.approval import orders_sha256
from tradeloop.lib.broker.live_state import (
    LiveBrokerSnapshot,
    LiveReconciliationStatus,
    compute_reconciliation,
    live_reconcile_allows_route,
    persist_reconciliation,
    refresh_live_reconciliation,
)
from tradeloop.lib.broker.paper_broker import OrderTicket
from tradeloop.lib.config import load_settings
from tradeloop.tests.test_orchestrator import _fresh_root

_SETTINGS = load_settings(Path(__file__).resolve().parents[1] / "config" / "settings.yaml")


def _snap(checked_at=None, auth_ok=True, holdings=None, open_orders=None, cash=1_000_000.0):
    return LiveBrokerSnapshot(
        checked_at=checked_at or datetime.now(timezone.utc).isoformat(),
        auth_ok=auth_ok, holdings=holdings or {}, open_orders=open_orders or [],
        available_cash_inr=cash)


def test_matching_holdings_pass():
    snap = _snap(holdings={"RELIANCE": 10})
    status = compute_reconciliation(snap, [OrderTicket("RELIANCE", "SELL", 5, 1000)],
                                    expected_book={"RELIANCE": 10})
    assert status.ok is True
    assert status.reasons == []


def test_quantity_mismatch_blocks():
    snap = _snap(holdings={"RELIANCE": 7})
    status = compute_reconciliation(snap, [], expected_book={"RELIANCE": 10})
    assert status.ok is False
    assert any("holdings mismatch" in r for r in status.reasons)


def test_sell_exceeding_broker_held_blocks():
    snap = _snap(holdings={"RELIANCE": 5})
    status = compute_reconciliation(snap, [OrderTicket("RELIANCE", "SELL", 10, 1000)],
                                    expected_book={"RELIANCE": 5})
    assert status.ok is False
    assert any("exceeds broker-held" in r for r in status.reasons)


def test_duplicate_open_order_blocks():
    snap = _snap(open_orders=[{"symbol": "RELIANCE", "side": "BUY", "quantity": 5}])
    status = compute_reconciliation(snap, [OrderTicket("RELIANCE", "BUY", 1, 1000)],
                                    expected_book={})
    assert status.ok is False
    assert status.open_order_conflicts == ["RELIANCE/BUY"]
    assert any("duplicate open order" in r for r in status.reasons)


def test_missing_broker_snapshot_blocks_live():
    assert live_reconcile_allows_route(Path("/tmp/does_not_exist_xyz")) is False


def test_stale_auth_blocks():
    snap = _snap(auth_ok=False)
    status = compute_reconciliation(snap, [], expected_book={})
    assert status.ok is False
    assert any("auth failure" in r for r in status.reasons)
    # Persisted not-ok result also blocks the route gate.
    p = Path("/tmp/recon_auth")
    p.mkdir(parents=True, exist_ok=True)
    persist_reconciliation(p, LiveReconciliationStatus(
        ok=False, reasons=["broker auth failure"], symbols_checked=[],
        open_order_conflicts=[], checked_at=datetime.now(timezone.utc).isoformat()))
    assert live_reconcile_allows_route(p) is False


def test_stale_checked_at_blocks():
    old = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
    status = LiveReconciliationStatus(
        ok=True, reasons=[], symbols_checked=["RELIANCE"], open_order_conflicts=[],
        checked_at=old)
    p = Path("/tmp/recon_stale")
    p.mkdir(parents=True, exist_ok=True)
    persist_reconciliation(p, status)
    assert live_reconcile_allows_route(p) is False
    # A fresh ok result is accepted.
    fresh = LiveReconciliationStatus(
        ok=True, reasons=[], symbols_checked=["RELIANCE"], open_order_conflicts=[],
        checked_at=datetime.now(timezone.utc).isoformat())
    persist_reconciliation(p, fresh)
    assert live_reconcile_allows_route(p) is True


def test_missing_snapshot_blocks_live_route(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: __import__("datetime").date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: True)
    run_dir = root / "runs" / "lr"
    run_dir.mkdir(parents=True)
    orders = [{"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000}]
    (run_dir / "orders.json").write_text(json.dumps({"orders": orders}), encoding="utf-8")
    (run_dir / "approval.json").write_text(json.dumps({
        "approved_live": True,
        "orders_sha256": orders_sha256(run_dir / "orders.json")}), encoding="utf-8")
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 2
    assert not (run_dir / "fills.json").exists()


def test_paper_route_ignores_missing_live_snapshot(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: __import__("datetime").date(2026, 7, 1))
    called = []
    monkeypatch.setattr(orchestrator, "live_reconcile_allows_route",
                        lambda *a, **k: called.append(1) or False)
    run_dir = root / "runs" / "paper"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000},
    ]}), encoding="utf-8")
    orchestrator.route_cycle(run_dir, root=root)  # live disabled -> paper path
    assert called == []  # paper never consults the broker snapshot


def _fake_npm(run_dir, snapshot_text=None, returncode=0):
    def fake_run(*a, **k):
        if snapshot_text is not None:
            (run_dir / "live_broker_snapshot.json").write_text(snapshot_text, encoding="utf-8")
        return types.SimpleNamespace(returncode=returncode)
    return fake_run


def test_refresh_fetch_failure_blocks(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_npm(run_dir, returncode=1))
    status = refresh_live_reconciliation(run_dir, tmp_path, run_dir / "orders.json")
    assert status.ok is False
    assert live_reconcile_allows_route(run_dir) is False


def test_refresh_uses_npm_project_root_when_app_root_has_no_package_json(tmp_path, monkeypatch):
    app_root = tmp_path / "tradeloop"
    app_root.mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    run_dir = app_root / "run"
    run_dir.mkdir()
    orders_path = run_dir / "orders.json"
    orders_path.write_text(json.dumps({"orders": []}), encoding="utf-8")
    captured = {}

    def fake_run(*args, **kwargs):
        captured["cwd"] = kwargs["cwd"]
        return types.SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    refresh_live_reconciliation(run_dir, app_root, orders_path)
    assert captured["cwd"] == tmp_path


def test_refresh_npm_missing_blocks(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")

    def raise_missing(*a, **k):
        raise FileNotFoundError("npm")
    monkeypatch.setattr(subprocess, "run", raise_missing)
    status = refresh_live_reconciliation(run_dir, tmp_path, run_dir / "orders.json")
    assert status.ok is False
    assert live_reconcile_allows_route(run_dir) is False


def test_refresh_malformed_snapshot_blocks(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_npm(run_dir, snapshot_text="{not json"))
    status = refresh_live_reconciliation(run_dir, tmp_path, run_dir / "orders.json")
    assert status.ok is False
    assert any("missing or malformed" in r for r in status.reasons)


def test_refresh_missing_snapshot_blocks(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_npm(run_dir))  # writes nothing
    status = refresh_live_reconciliation(run_dir, tmp_path, run_dir / "orders.json")
    assert status.ok is False


def test_refresh_bad_live_book_blocks(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "live_book.json").write_text("{broken", encoding="utf-8")
    snap = LiveBrokerSnapshot(
        checked_at=datetime.now(timezone.utc).isoformat(), auth_ok=True,
        holdings={}, open_orders=[], available_cash_inr=100000.0)
    monkeypatch.setattr(subprocess, "run", _fake_npm(run_dir, snapshot_text=json.dumps({
        "checked_at": snap.checked_at, "auth_ok": True, "holdings": {},
        "open_orders": [], "available_cash_inr": 100000.0})))
    status = refresh_live_reconciliation(run_dir, tmp_path, run_dir / "orders.json")
    assert status.ok is False
    assert any("malformed" in r for r in status.reasons)


def test_refresh_success_persists_ok(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000},
    ]}), encoding="utf-8")
    snap = LiveBrokerSnapshot(
        checked_at=datetime.now(timezone.utc).isoformat(), auth_ok=True,
        holdings={"RELIANCE": 1}, open_orders=[], available_cash_inr=100000.0)
    monkeypatch.setattr(subprocess, "run", _fake_npm(run_dir, snapshot_text=json.dumps({
        "checked_at": snap.checked_at, "auth_ok": True, "holdings": {"RELIANCE": 1},
        "open_orders": [], "available_cash_inr": 100000.0})))
    status = refresh_live_reconciliation(run_dir, tmp_path, run_dir / "orders.json")
    assert status.ok is True
    assert live_reconcile_allows_route(run_dir) is True


def _auto_live_settings():
    return dataclasses.replace(_SETTINGS, approval_mode="auto", allow_auto_live=True)


def _live_route_fixture(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: __import__("datetime").date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "load_settings", lambda *a, **k: _auto_live_settings())
    run_dir = root / "runs" / "live"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000},
    ]}), encoding="utf-8")
    return root, run_dir


def test_live_route_refreshes_before_routing(monkeypatch, tmp_path):
    root, run_dir = _live_route_fixture(monkeypatch, tmp_path)
    called = []

    def fake_refresh(run_dir, root, orders_path):
        called.append(1)
        ok = LiveReconciliationStatus(
            ok=True, reasons=[], symbols_checked=["RELIANCE"], open_order_conflicts=[],
            checked_at=datetime.now(timezone.utc).isoformat())
        persist_reconciliation(run_dir, ok)
        return ok
    monkeypatch.setattr(orchestrator, "refresh_live_reconciliation", fake_refresh)
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert called == [1]  # refresh happened before routing
    assert rc == 0
    assert (run_dir / "fills.json").exists()


def test_live_route_blocks_when_refresh_not_ok(monkeypatch, tmp_path):
    root, run_dir = _live_route_fixture(monkeypatch, tmp_path)

    def fake_refresh(run_dir, root, orders_path):
        bad = LiveReconciliationStatus(
            ok=False, reasons=["holdings mismatch RELIANCE"], symbols_checked=["RELIANCE"],
            open_order_conflicts=[], checked_at=datetime.now(timezone.utc).isoformat())
        persist_reconciliation(run_dir, bad)
        return bad
    monkeypatch.setattr(orchestrator, "refresh_live_reconciliation", fake_refresh)
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 2
    assert not (run_dir / "fills.json").exists()


def test_paper_route_never_refreshes(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: __import__("datetime").date(2026, 7, 1))
    called = []
    monkeypatch.setattr(orchestrator, "refresh_live_reconciliation",
                        lambda *a, **k: called.append(1) or LiveReconciliationStatus(
                            ok=True, reasons=[], symbols_checked=[], open_order_conflicts=[],
                            checked_at=datetime.now(timezone.utc).isoformat()))
    run_dir = root / "runs" / "paper"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000},
    ]}), encoding="utf-8")
    orchestrator.route_cycle(run_dir, root=root)  # live disabled -> paper path
    assert called == []  # paper never runs the broker snapshot producer
