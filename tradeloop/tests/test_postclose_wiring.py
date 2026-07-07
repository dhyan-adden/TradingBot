"""P4 Task 11 (redesigned for the propose/approve split): the auditor is wired
into route_cycle (the approve phase), NOT run_cycle (propose never routes). The
audit runs AFTER fills are persisted - the one moment orders.json + fills.json +
the fresh ledger are all consistent - and is observability-only: it must never
fail an already-committed route.
"""
import json
from datetime import date

from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger
from tradeloop.tests.test_orchestrator import _fresh_root  # copies real config into an isolated root


def test_postclose_audit_helper_flags_bad_filled_order(tmp_path):
    # A bad order (non-universe symbol) that nevertheless FILLED -> the gate should
    # have caught it -> the control test flags a material_weakness.
    root = _fresh_root(tmp_path)
    run_dir = root / "runs" / "2026-07-02_1600_postclose"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({
        "mode": "postclose", "live_orders_enabled": False,
        "orders": [{"ticker": "ZZZZ", "side": "BUY", "quantity": 100,
                    "price": 200.0, "status": "FILLED"}],
        "held": [],
    }), encoding="utf-8")
    (run_dir / "fills.json").write_text(json.dumps(
        [{"mode": "paper", "status": "FILLED", "payload": {"symbol": "ZZZZ"}}]), encoding="utf-8")
    led = Ledger(root / "state" / "ledger.db")
    led.append({"type": ORDER_FILLED, "order_id": "PAPER-1", "symbol": "ZZZZ",
                "side": "BUY", "quantity": 100, "fill_price": 200.0,
                "product": "CNC", "status": "FILLED"})

    orchestrator._run_postclose_audit(run_dir, root=root, memory_root=root / "memory",
                                      run_id="R1", timestamp="2026-07-02T16:00")

    assert (run_dir / "40_reconcile.md").exists()
    controls = json.loads((run_dir / "controls.json").read_text(encoding="utf-8"))
    assert (root / "memory" / "strategy_performance.md").exists()
    assert any(d["severity"] == "material_weakness" for d in controls["deficiencies"])


def test_near_cap_filled_batch_is_not_falsely_flagged(tmp_path):
    # Regression: two same-sector FILLED orders at ~24% each (48% < the 50% sector cap)
    # must NOT be flagged. Re-checking against the POST-fill book double-counts each
    # position (~72%) and false-flags both as material_weakness; the pre-route
    # reconstruction re-evaluates each against the gate's real pre-trade context.
    root = _fresh_root(tmp_path)  # universe.yaml: HDFCBANK + SBIN are both Financial Services
    run_dir = root / "runs" / "2026-07-07_1310_premarket"
    run_dir.mkdir(parents=True)
    orders = [{"ticker": "HDFCBANK", "side": "BUY", "quantity": 30, "price": 800.0,
               "hard_stop": 776.0, "status": "FILLED"},
              {"ticker": "SBIN", "side": "BUY", "quantity": 30, "price": 800.0,
               "hard_stop": 776.0, "status": "FILLED"}]
    (run_dir / "orders.json").write_text(json.dumps(
        {"mode": "premarket", "orders": orders, "held": []}), encoding="utf-8")
    (run_dir / "fills.json").write_text(json.dumps(
        [{"mode": "paper", "status": "FILLED", "payload": {"symbol": "HDFCBANK"}},
         {"mode": "paper", "status": "FILLED", "payload": {"symbol": "SBIN"}}]), encoding="utf-8")
    led = Ledger(root / "state" / "ledger.db")
    for i, sym in enumerate(("HDFCBANK", "SBIN")):
        led.append({"type": ORDER_FILLED, "order_id": f"PAPER-{i}", "symbol": sym,
                    "side": "BUY", "quantity": 30, "fill_price": 800.0,
                    "product": "CNC", "status": "FILLED"})

    orchestrator._run_postclose_audit(run_dir, root=root, memory_root=root / "memory",
                                      run_id="R1", timestamp="2026-07-07T16:00")

    report = json.loads((run_dir / "controls.json").read_text(encoding="utf-8"))
    assert not any(d["severity"] == "material_weakness" for d in report["deficiencies"]), report
    assert report["tested"] == 2 and report["passed"] == 2


def test_route_cycle_invokes_audit_after_successful_route(monkeypatch, tmp_path):
    # Wiring guard: a successful route MUST fire the audit. Dropping the call would
    # otherwise pass the whole suite silently (the accountability layer never runs).
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))  # a weekday
    run_dir = root / "runs" / "2026-07-01_0800_premarket"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000,
         "hard_stop": 950.0}]}), encoding="utf-8")

    called = {}
    real = orchestrator._run_postclose_audit

    def spy(rd, **kw):
        called["run_dir"] = rd
        return real(rd, **kw)

    monkeypatch.setattr(orchestrator, "_run_postclose_audit", spy)

    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    assert (run_dir / "fills.json").exists()          # the route actually filled
    assert called.get("run_dir") == run_dir           # the audit fired
    assert (run_dir / "controls.json").exists()        # via the real helper


def test_audit_failure_does_not_fail_the_route(monkeypatch, tmp_path, capsys):
    # The route already committed fills to the ledger; a throwing audit must not
    # turn a good route into a failure. It records the error and still returns OK.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = root / "runs" / "2026-07-01_0801_premarket"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000,
         "hard_stop": 950.0}]}), encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("audit exploded")

    monkeypatch.setattr(orchestrator, "_run_postclose_audit", boom)

    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    assert "tradeloop_route=OK" in capsys.readouterr().out
    assert (run_dir / "audit_error.txt").exists()
