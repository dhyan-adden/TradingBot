"""Phase 8: live human-in-loop approval is explicit and bound to orders.json."""
from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.approval import (
    ApprovalStatus,
    orders_sha256,
    requires_live_human_approval,
    validate_approval,
)
from tradeloop.lib.config import load_settings
from tradeloop.tests.test_orchestrator import _fresh_root

REPO_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS = load_settings(REPO_ROOT / "tradeloop" / "config" / "settings.yaml")


def _write_orders(run_dir: Path, orders: list) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": orders}), encoding="utf-8")
    return run_dir


def test_missing_approval_blocks():
    run_dir = _write_orders(Path("/tmp/noappr"), [{"ticker": "X", "side": "BUY", "quantity": 1, "price": 10}])
    status = validate_approval(run_dir, run_dir / "orders.json")
    assert status.ok is False
    assert any("no approval.json" in r for r in status.reasons)


def test_wrong_hash_blocks():
    run_dir = _write_orders(Path("/tmp/wronghash"), [{"ticker": "X", "side": "BUY", "quantity": 1, "price": 10}])
    (run_dir / "approval.json").write_text(json.dumps({
        "approved_live": True, "orders_sha256": "deadbeef"}), encoding="utf-8")
    status = validate_approval(run_dir, run_dir / "orders.json")
    assert status.ok is False
    assert any("orders_sha256 mismatch" in r for r in status.reasons)


def test_correct_hash_allows():
    run_dir = _write_orders(Path("/tmp/okhash"), [{"ticker": "X", "side": "BUY", "quantity": 1, "price": 10}])
    (run_dir / "approval.json").write_text(json.dumps({
        "approved_live": True,
        "orders_sha256": orders_sha256(run_dir / "orders.json")}), encoding="utf-8")
    status = validate_approval(run_dir, run_dir / "orders.json")
    assert status.ok is True
    assert status.approved_live is True


def test_auto_mode_skips_human_approval():
    assert requires_live_human_approval(_SETTINGS) is True
    auto = dataclasses.replace(_SETTINGS, approval_mode="auto")
    assert requires_live_human_approval(auto) is False


def test_live_human_approval_required_blocks_route(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: True)
    run_dir = root / "runs" / "appr"
    _write_orders(run_dir, [{"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000}])
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 2
    assert not (run_dir / "fills.json").exists()


def test_auto_mode_ignores_stale_human_approval(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: True)
    auto_settings = dataclasses.replace(_SETTINGS, approval_mode="auto")
    monkeypatch.setattr(orchestrator, "load_settings", lambda *a, **k: auto_settings)
    called = []
    monkeypatch.setattr(orchestrator, "validate_approval",
                        lambda *a, **k: called.append(1) or ApprovalStatus(False, ["x"]))
    run_dir = root / "runs" / "auto"
    _write_orders(run_dir, [{"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000}])
    (run_dir / "approval.json").write_text(json.dumps({
        "approved_live": True, "orders_sha256": "stale"}), encoding="utf-8")
    orchestrator.route_cycle(run_dir, root=root)
    assert called == []  # auto mode never consults the human approval artifact


def test_auto_live_blocked_without_allow_auto_live(monkeypatch, tmp_path, capsys):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: True)
    auto_settings = dataclasses.replace(_SETTINGS, approval_mode="auto", allow_auto_live=False)
    monkeypatch.setattr(orchestrator, "load_settings", lambda *a, **k: auto_settings)
    approval_called = []
    reconcile_called = []
    monkeypatch.setattr(orchestrator, "validate_approval",
                        lambda *a, **k: approval_called.append(1) or ApprovalStatus(False, ["x"]))
    monkeypatch.setattr(orchestrator, "live_reconcile_allows_route",
                        lambda *a, **k: reconcile_called.append(1) or False)
    run_dir = root / "runs" / "auto_disabled"
    _write_orders(run_dir, [{"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000}])
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 2
    assert "AUTO_LIVE_DISABLED" in capsys.readouterr().out
    assert approval_called == []
    assert reconcile_called == []  # blocked before broker-state refresh
    assert not (run_dir / "fills.json").exists()


def test_auto_live_with_allow_auto_live_reaches_reconcile(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: True)
    auto_settings = dataclasses.replace(_SETTINGS, approval_mode="auto", allow_auto_live=True)
    monkeypatch.setattr(orchestrator, "load_settings", lambda *a, **k: auto_settings)
    approval_called = []
    monkeypatch.setattr(orchestrator, "validate_approval",
                        lambda *a, **k: approval_called.append(1) or ApprovalStatus(False, ["x"]))
    reconcile_called = []
    monkeypatch.setattr(orchestrator, "live_reconcile_allows_route",
                        lambda *a, **k: reconcile_called.append(1) or False)
    run_dir = root / "runs" / "auto_enabled"
    _write_orders(run_dir, [{"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000}])
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 2  # still blocked: no fresh reconciliation present
    assert approval_called == []  # auto never consults the human approval artifact
    assert reconcile_called == [1]  # reached the broker-state gate


def test_paper_route_ignores_allow_auto_live(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    auto_settings = dataclasses.replace(_SETTINGS, approval_mode="auto", allow_auto_live=False)
    monkeypatch.setattr(orchestrator, "load_settings", lambda *a, **k: auto_settings)
    run_dir = root / "runs" / "paper_auto"
    _write_orders(run_dir, [{"ticker": "RELIANCE", "side": "BUY", "quantity": 1, "price": 1000}])
    rc = orchestrator.route_cycle(run_dir, root=root)  # live disabled -> paper path
    assert rc == 0
    assert (run_dir / "fills.json").exists()
