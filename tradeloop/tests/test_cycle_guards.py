"""Guard-branch and e2e coverage for the split cycle (propose/approve).

Test plan - each test exists to kill a specific plausible bug:
- Failure branches (money-path guards that were previously untested):
  DAG timeout, lock contention (both phases), LIVE_NOT_READY (both phases),
  route without orders.json, holiday arriving between propose and approve.
- Edge: adhoc intake narrowing - with a PM stage (orders flow) and without one
  (research-only; previously crashed with FileNotFoundError).
- E2E (real subprocess, real CLI, real exit codes): argparse wiring and the
  file guards. The happy routing path is NOT CLI-tested because the holiday
  gate reads the real clock (would flake on weekends); it is covered
  in-process where the date is controllable, and by live smoke runs.
- E2E: SELL exit against a hydrated position through route_cycle -> book.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import Ledger
from tradeloop.lib.broker import paper_book
from tradeloop.lib.broker.paper_broker import Fill
from tradeloop.tests.test_orchestrator import _fresh_root
from tradeloop.tests.test_reasoning_wiring import StageFakeClient
from tradeloop.lib.llm import schemas

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- failure branches -------------------------------------------------------

def test_dag_timeout_returns_minus_one(tmp_path):
    # Deadline already expired: no stage may run, no orders may be written.
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "openrouter", -1,
                                     client=StageFakeClient())
    assert rc == -1
    assert not (tmp_path / "orders.json").exists()


def test_run_cycle_reports_timeout(monkeypatch, tmp_path, capsys):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "_prepare",
                        lambda mode, request="", root=None: tmp_path / "rd")
    (tmp_path / "rd").mkdir()
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: -1)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 1
    assert "TIMEOUT" in capsys.readouterr().out


def test_propose_locked_when_another_cycle_holds_lock(monkeypatch, tmp_path, capsys):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    reasoned = {"n": 0}
    monkeypatch.setattr(orchestrator, "_run_reasoning",
                        lambda *a, **k: reasoned.__setitem__("n", 1) or 0)
    with orchestrator._global_lock(root) as held:
        assert held
        rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert reasoned["n"] == 0  # never reasoned while locked out
    assert "LOCKED" in capsys.readouterr().out


def test_route_locked_when_another_cycle_holds_lock(monkeypatch, tmp_path, capsys):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = root / "runs" / "locked"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000},
    ]}), encoding="utf-8")
    with orchestrator._global_lock(root) as held:
        assert held
        rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    assert not (run_dir / "fills.json").exists()  # nothing routed while locked
    assert "LOCKED" in capsys.readouterr().out


def test_live_not_ready_blocks_both_phases(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    monkeypatch.setattr(orchestrator, "live_enabled", lambda: True)
    monkeypatch.setattr(orchestrator, "live_promotion_ready", lambda *a, **k: False)
    assert orchestrator.run_cycle("premarket", root=root) == 2
    run_dir = root / "runs" / "lnr"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
    assert orchestrator.route_cycle(run_dir, root=root) == 2
    assert not (run_dir / "fills.json").exists()


def test_route_without_orders_file_fails_loud(tmp_path, capsys):
    root = _fresh_root(tmp_path)
    empty = root / "runs" / "empty"
    empty.mkdir(parents=True)
    assert orchestrator.route_cycle(empty, root=root) == 1
    assert "NO_ORDERS_FILE" in capsys.readouterr().out


def test_route_skips_when_holiday_arrives_between_propose_and_approve(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 1, 26))  # Republic Day
    run_dir = root / "runs" / "hol"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000},
    ]}), encoding="utf-8")
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    assert not (run_dir / "fills.json").exists()


# --- adhoc narrowing edge cases ---------------------------------------------

class AdhocFakeClient(StageFakeClient):
    def __init__(self, required_stages):
        self.required_stages = required_stages

    def call_json(self, role, system, user, schema, model=None):
        if schema is schemas.AdhocIntake:
            return schema.model_validate({
                "classification": "market_research",
                "safe_interpretation": "scoped",
                "required_stages": self.required_stages,
                "refused_parts": [],
            })
        return super().call_json(role, system, user, schema, model)


def _adhoc_run_dir(tmp_path):
    d = tmp_path / "runs" / "adhoc"
    d.mkdir(parents=True)
    (d / "user_request.md").write_text("what looks good today?\n")
    (d / "00_context.md").write_text("# context\n")
    (d / "01_news_raw.md").write_text("# raw\n")
    return d


def test_adhoc_intake_narrows_dag(tmp_path):
    d = _adhoc_run_dir(tmp_path)
    client = AdhocFakeClient(["10_news.md", "41_pm_decision.md"])
    rc = orchestrator._run_reasoning(d, "adhoc", "openrouter", 1200, client=client)
    assert rc == 0
    assert (d / "10_news.json").exists()
    assert not (d / "11_sentiment.json").exists()   # narrowed away
    assert not (d / "30_trade_plan.json").exists()  # narrowed away
    orders = json.loads((d / "orders.json").read_text())
    assert orders["orders"][0]["ticker"] == "RELIANCE"


def test_adhoc_research_only_writes_empty_orders(tmp_path):
    # A research-only intake (no PM stage) must complete cleanly with an empty,
    # valid orders.json - not crash on the missing 41_pm_decision.json.
    d = _adhoc_run_dir(tmp_path)
    client = AdhocFakeClient(["10_news.md", "14_shortlist.md"])
    rc = orchestrator._run_reasoning(d, "adhoc", "openrouter", 1200, client=client)
    assert rc == 0
    orders = json.loads((d / "orders.json").read_text())
    assert orders["orders"] == [] and orders["held"] == []


# --- real-subprocess CLI e2e --------------------------------------------------

def test_cli_route_guards_e2e(tmp_path):
    root = _fresh_root(tmp_path)

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "tradeloop.orchestrator", *args],
            capture_output=True, text=True, cwd=str(REPO_ROOT))

    # argparse guard: route without a run_dir is a usage error
    proc = cli("route", "--root", str(root))
    assert proc.returncode == 2

    # missing orders.json -> loud failure through the real CLI
    empty = root / "runs" / "cli_empty"
    empty.mkdir(parents=True)
    proc = cli("route", str(empty), "--root", str(root))
    assert proc.returncode == 1
    assert "NO_ORDERS_FILE" in proc.stdout

    # pre-existing fills.json -> double-route refused through the real CLI
    routed = root / "runs" / "cli_routed"
    routed.mkdir(parents=True)
    (routed / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
    (routed / "fills.json").write_text("[]", encoding="utf-8")
    proc = cli("route", str(routed), "--root", str(root))
    assert proc.returncode == 1
    assert "ALREADY_ROUTED" in proc.stdout


# --- SELL exit through the full approve path ---------------------------------

def test_sell_exit_routes_and_updates_book(monkeypatch, tmp_path):
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    book_path = root / "state" / "paper_book.jsonl"
    paper_book.append(
        book_path,
        [Fill("SEED", "RELIANCE", "BUY", 20, 1000.0, "FILLED", "CNC")],
        hard_stops={"RELIANCE": 950.0},
    )

    run_dir = root / "runs" / "sell"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "SELL", "quantity": 20, "price": 1100},
    ]}), encoding="utf-8")

    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    assert any(f.get("status") == "FILLED" for f in fills)
    # position fully exited and the exit persisted to the ledger
    rehydrated = orchestrator.hydrate(book_path, 100000)
    assert rehydrated.positions.get("RELIANCE", 0) == 0
    sells = Ledger(book_path).replay(["paper.order.filled"])
    assert any(e["symbol"] == "RELIANCE" and e["side"] == "SELL" for e in sells)
    Ledger(book_path).verify_chain()
