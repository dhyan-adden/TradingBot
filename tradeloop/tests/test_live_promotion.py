"""Phase 6: live promotion is one source of truth (ledger + audit), never markdown."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger
from tradeloop.lib.config import load_settings
from tradeloop.lib.live.promotion import evaluate_live_promotion

_SETTINGS = load_settings(
    Path(__file__).resolve().parents[1] / "config" / "settings.yaml")


def _seed_closed_trades(led: Ledger, n: int) -> None:
    # n winning round trips on TCS, each +3R (entry 100, stop 90, exit 130).
    for i in range(n):
        led.append({"type": ORDER_FILLED, "order_id": f"B{i}", "symbol": "TCS",
                    "side": "BUY", "quantity": 10, "fill_price": 100.0,
                    "product": "CNC", "hard_stop": 90.0})
        led.append({"type": ORDER_FILLED, "order_id": f"S{i}", "symbol": "TCS",
                    "side": "SELL", "quantity": 10, "fill_price": 130.0,
                    "product": "CNC", "hard_stop": 0.0})


def _root_with_ledger(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    Ledger(state / "ledger.db")  # creates the schema
    return tmp_path


def _routed_run(run_dir: Path, clean: bool = True) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "fills.json").write_text(json.dumps([{"status": "FILLED"}]), encoding="utf-8")
    if clean:
        (run_dir / "controls.json").write_text(
            json.dumps({"tested": 1, "passed": 1, "deficiencies": []}), encoding="utf-8")
        (run_dir / "40_reconcile.md").write_text(
            "# Reconciliation\n\n- clean: all sources agree\n", encoding="utf-8")
    else:
        (run_dir / "audit_error.txt").write_text("boom", encoding="utf-8")


def test_missing_ledger_not_ready(tmp_path):
    status = evaluate_live_promotion(tmp_path, _SETTINGS)
    assert status.ready is False
    assert any("no ledger" in r for r in status.reasons)


def test_empty_paper_ledger_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert status.closed_paper_trades == 0
    assert any("closed_paper_trades=0" in r for r in status.reasons)


def test_tampered_ledger_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    led = Ledger(root / "state" / "ledger.db")
    _seed_closed_trades(led, 1)
    conn = sqlite3.connect(str(root / "state" / "ledger.db"))
    conn.execute("UPDATE events SET row_hash='deadbeef' WHERE seq=1")
    conn.commit()
    conn.close()
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert any("tampered" in r for r in status.reasons)


def test_59_closed_trades_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    _seed_closed_trades(Ledger(root / "state" / "ledger.db"), 59)
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert status.closed_paper_trades == 59
    assert any("closed_paper_trades=" in r for r in status.reasons)


def test_60_trades_dirty_audit_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path_dir := tmp_path)
    _seed_closed_trades(Ledger(root / "state" / "ledger.db"), 60)
    _routed_run(root / "runs" / "r1", clean=False)
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert any("audit gate not clean" in r for r in status.reasons)


def test_60_trades_clean_audit_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    _seed_closed_trades(Ledger(root / "state" / "ledger.db"), 60)
    _routed_run(root / "runs" / "r1", clean=True)
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is True
    assert status.closed_paper_trades == 60


def test_markdown_live_ready_literal_has_no_effect(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "strategy_performance.md").write_text(
        "live_ready: true\npaper_trades: 9999\n", encoding="utf-8")
    status = evaluate_live_promotion(tmp_path, _SETTINGS)
    assert status.ready is False  # no ledger, markdown ignored


def test_markdown_60_trades_failing_expectancy_not_ready(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "strategy_performance.md").write_text(
        "paper_trades: 60\nwin_rate: 0.7\nexpectancy_r: -0.2\n", encoding="utf-8")
    status = evaluate_live_promotion(tmp_path, _SETTINGS)
    assert status.ready is False
    assert status.closed_paper_trades == 0  # metrics came from ledger, not markdown


def test_missing_controls_json_on_routed_run_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    _seed_closed_trades(Ledger(root / "state" / "ledger.db"), 60)
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "fills.json").write_text(json.dumps([{"status": "FILLED"}]), encoding="utf-8")
    (run / "40_reconcile.md").write_text(
        "# Reconciliation\n\n- clean: all sources agree\n", encoding="utf-8")
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert any("audit gate not clean" in r for r in status.reasons)


def test_critical_deficiency_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    _seed_closed_trades(Ledger(root / "state" / "ledger.db"), 60)
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "fills.json").write_text(json.dumps([{"status": "FILLED"}]), encoding="utf-8")
    (run / "controls.json").write_text(json.dumps({
        "tested": 1, "passed": 0,
        "deficiencies": [{"symbol": "TCS", "severity": "material_weakness",
                          "kind": "bad", "detail": "x"}]}), encoding="utf-8")
    (run / "40_reconcile.md").write_text(
        "# Reconciliation\n\n- clean: all sources agree\n", encoding="utf-8")
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert any("audit gate not clean" in r for r in status.reasons)


def test_missing_or_dirty_reconcile_not_ready(tmp_path):
    root = _root_with_ledger(tmp_path)
    _seed_closed_trades(Ledger(root / "state" / "ledger.db"), 60)
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "fills.json").write_text(json.dumps([{"status": "FILLED"}]), encoding="utf-8")
    (run / "controls.json").write_text(
        json.dumps({"tested": 1, "passed": 1, "deficiencies": []}), encoding="utf-8")
    (run / "40_reconcile.md").write_text(
        "# Reconciliation\n\n- TCS: qty ledger=10 vs book=9\n", encoding="utf-8")
    status = evaluate_live_promotion(root, _SETTINGS)
    assert status.ready is False
    assert any("audit gate not clean" in r for r in status.reasons)
