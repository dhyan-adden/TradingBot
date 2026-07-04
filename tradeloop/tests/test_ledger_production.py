"""E2E proof that route_cycle wires the ledger into the real production path:
every route logs a risk.verdict AND a paper.order.filled event, the chain
verifies, positions hydrate correctly, and a tampered ledger halts routing."""
import json
import sqlite3
from datetime import date

from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import Ledger
from tradeloop.tests.test_orchestrator import _fresh_root


def _seed_run(root, name="prod"):
    run_dir = root / "runs" / name
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000, "hard_stop": 950.0},
    ]}), encoding="utf-8")
    return run_dir


def test_empty_fills_placeholder_does_not_block_route(monkeypatch, tmp_path):
    # prepare_cycle pre-creates an empty fills.json placeholder; it must NOT trip
    # the double-routing guard, or the approve step can never run on a real cycle.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = _seed_run(root, name="placeholder")
    (run_dir / "fills.json").write_text("[]\n", encoding="utf-8")

    assert orchestrator.route_cycle(run_dir, root=root) == 0


def test_nonempty_fills_still_blocks_reroute(monkeypatch, tmp_path, capsys):
    # the guard's real job: once actual fills exist, refuse to route again.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = _seed_run(root, name="reroute")
    (run_dir / "fills.json").write_text(
        json.dumps([{"symbol": "RELIANCE", "quantity": 20, "status": "FILLED"}]),
        encoding="utf-8")

    assert orchestrator.route_cycle(run_dir, root=root) == 1
    assert "ALREADY_ROUTED" in capsys.readouterr().out


def test_route_cycle_logs_verdict_and_fill_and_verifies_chain(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = _seed_run(root)

    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0

    book_path = root / "state" / "ledger.db"
    assert book_path.exists()
    led = Ledger(book_path)
    led.verify_chain()  # must not raise

    verdicts = led.replay(["risk.verdict"])
    fills = led.replay(["paper.order.filled"])
    assert len(verdicts) == 1
    assert verdicts[0]["symbol"] == "RELIANCE" and verdicts[0]["approved"] is True
    assert len(fills) == 1
    assert fills[0]["symbol"] == "RELIANCE" and fills[0]["quantity"] == 20

    rehydrated = orchestrator.hydrate(book_path, 100000)
    assert rehydrated.positions == {"RELIANCE": 20}


def test_tampered_ledger_halts_the_next_route_cycle(monkeypatch, tmp_path, capsys):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = _seed_run(root, name="prod1")
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0

    book_path = root / "state" / "ledger.db"
    conn = sqlite3.connect(str(book_path))
    conn.execute("UPDATE events SET payload_json = ? WHERE seq = 1",
                 (json.dumps({"type": "tampered", "ts": "2026-07-01T00:00:00+00:00"}),))
    conn.commit()
    conn.close()

    run_dir2 = _seed_run(root, name="prod2")
    rc2 = orchestrator.route_cycle(run_dir2, root=root)
    out = capsys.readouterr().out
    assert rc2 == 1
    assert "LEDGER_TAMPERED" in out
    # the second cycle must not have routed - no fills.json written
    assert not (run_dir2 / "fills.json").exists()
