"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from tradeloop.lib.audit.ledger import Ledger, LedgerTamperError
from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.broker.paper_book import append as append_book, hydrate
from tradeloop.lib.broker.router import live_enabled, live_promotion_ready, route_orders_file
from tradeloop.lib.config import load_settings
from tradeloop.lib.data.evidence import validate_evidence
from tradeloop.lib.data.snapshot import load_snapshot
from tradeloop.lib.llm import stages
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.schemas import PMDecision
from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.util.holidays import is_nse_holiday
from tradeloop.scripts.prepare_cycle import prepare as _prepare

ROOT = Path(__file__).resolve().parent


def _gate_holiday(today: date) -> str | None:
    return "nse_holiday" if is_nse_holiday(today) else None


def _gate_kill_switch(root: Path) -> str | None:
    return "kill_switch" if kill_switch_active(root) else None


def _today() -> date:
    return date.today()


def _run_reasoning(run_dir: Path, mode: str, backend: str, timeout: int, client=None) -> int:
    """Dispatch reasoning to the selected backend, then return an int exit code
    matching P0's contract: -1 on cycle-timeout (run_cycle -> TIMEOUT, exit 1),
    0 on success, nonzero on failure.

    Both backends write a schema-valid orders.json into run_dir; the separate
    route phase then validates + gates it identically (evaluate() on every
    order), so the risk controls are backend-independent.

    - "openrouter" -> the in-process OpenRouter DAG (the P1 engine): cheap,
                      zero-tool models, full provenance audit. Default - the
                      "propose" half of the propose/approve split cycle.
    - "claude"     -> Claude Code subagents on your subscription (Opus master +
                      Haiku/Sonnet/Opus teams), for adhoc/research runs.
    """
    backend = (backend or "openrouter").lower()
    if backend == "claude":
        return _run_reasoning_claude(run_dir, mode, timeout)
    if backend == "openrouter":
        return _run_reasoning_openrouter(run_dir, mode, timeout, client)
    raise ValueError(f"unknown reasoning backend {backend!r} (use claude|openrouter)")


def _run_reasoning_claude(run_dir: Path, mode: str, timeout: int) -> int:
    """Reason via the Claude Code subagent backend (your subscription). The Opus
    master orchestrator (run_cycle.sh claude path) dispatches each team as a
    Claude Code subagent, writing artifacts + orders.json into the pinned
    run_dir. No OpenRouter. -1 on timeout, else the child exit code."""
    script = ROOT / "scripts" / "run_cycle.sh"
    env = dict(os.environ, TRADELOOP_AGENT="claude", TRADELOOP_RUN_DIR=str(run_dir))
    try:
        proc = subprocess.run(["bash", str(script), mode], env=env,
                              cwd=str(ROOT.parent), timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1
    return proc.returncode


def _run_reasoning_openrouter(run_dir: Path, mode: str, timeout: int, client=None) -> int:
    """In-process OpenRouter DAG: each stage returns a validated pydantic form
    written to run_dir/<stage>.json; Python - not the LLM - then serialises
    orders.json from the validated PMDecision (route_orders_file reads the
    OrdersFile shape and runs evaluate() on every order)."""
    client = client or LLMClient(audit_path=run_dir / "llm_calls.jsonl")
    deadline = time.monotonic() + timeout  # bound the DAG exactly as P0's subprocess timeout= did

    dag = list(stages.DAG)
    if mode == "adhoc" and (run_dir / "user_request.md").exists():
        if time.monotonic() > deadline:
            return -1
        intake = stages.run_stage("05_adhoc_intake", run_dir, client)
        wanted = {s.removesuffix(".md") for s in intake.required_stages}
        if wanted:
            dag = [s for s in dag if s in wanted]

    for name in dag:
        if time.monotonic() > deadline:
            return -1
        stages.run_stage(name, run_dir, client)

    if "41_pm_decision" in dag:
        pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
        orders, held = pm.orders, pm.held
    else:  # research-only adhoc: no PM stage ran, so there is nothing to route
        orders, held = [], []
    orders_file = {
        "mode": mode,
        "live_orders_enabled": False,      # paper default; live only past promotion gate
        "generated_by": "tradeloop.reasoning.p1",
        "orders": [o.model_dump() for o in orders],
        "held": [o.model_dump() for o in held],
    }
    (run_dir / "orders.json").write_text(json.dumps(orders_file, indent=2), encoding="utf-8")
    return 0


@contextmanager
def _global_lock(root: Path):
    lock_path = root / "state" / "orchestrator.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # ponytail: global flock across all modes since the book is shared state;
    # per-mode locks only if throughput ever matters.
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def run_cycle(mode: str, request: str = "", root: Path = ROOT,
              backend: str | None = None) -> int:
    """Propose phase of the split cycle: gates -> reason -> validated orders.json,
    then STOP. Nothing routes until route_cycle(run_dir) is invoked - that
    invocation is the approval (a human/overseer reviewed the orders first)."""
    settings = load_settings(root / "config" / "settings.yaml")
    backend = backend or os.getenv("TRADELOOP_BACKEND", "openrouter")

    reason = _gate_holiday(_today())
    if reason:
        print(f"tradeloop_cycle=SKIP reason={reason}")
        return 0
    reason = _gate_kill_switch(root)
    if reason:
        print(f"tradeloop_cycle=HALT reason={reason}")
        return 0
    if live_enabled() and not live_promotion_ready(root, settings):
        print("tradeloop_cycle=LIVE_NOT_READY")
        return 2

    with _global_lock(root) as acquired:
        if not acquired:
            print("tradeloop_cycle=LOCKED")
            return 0
        run_dir = _prepare(mode, request, root=root) if _prepare_takes_root() else _prepare(mode, request)
        rc = _run_reasoning(run_dir, mode, backend, settings.cycle_timeout_seconds)
        if rc == -1:
            print("tradeloop_cycle=TIMEOUT")
            return 1
        if rc != 0:
            print(f"tradeloop_cycle=REASONING_FAILED rc={rc}")
            return 1

        # Validate now so a bad orders.json fails loudly at propose time, not
        # at approval time.
        try:
            n_orders = len(load_orders(run_dir / "orders.json").orders)
        except Exception:
            print("tradeloop_cycle=ORDERS_INVALID")
            return 1

        snap = load_snapshot(run_dir)
        if snap is not None:
            ev = validate_evidence(run_dir, snap)
            if not ev.ok:
                print(f"tradeloop_cycle=EVIDENCE_INVALID missing={len(ev.missing)} run_dir={run_dir}")
                return 1

        print(f"tradeloop_cycle=AWAITING_APPROVAL mode={mode} orders={n_orders} run_dir={run_dir}")
        return 0


def route_cycle(run_dir: Path, root: Path = ROOT) -> int:
    """Approval phase: review run_dir/orders.json first - invoking this routes it.
    Re-checks the safety gates (time has passed since propose), sends every order
    through evaluate() via route_orders_file, and persists fills to the book."""
    settings = load_settings(root / "config" / "settings.yaml")
    run_dir = Path(run_dir)
    orders_path = run_dir / "orders.json"
    fills_path = run_dir / "fills.json"
    if not orders_path.exists():
        print("tradeloop_route=NO_ORDERS_FILE")
        return 1
    if fills_path.exists():  # double-routing would double positions
        print("tradeloop_route=ALREADY_ROUTED")
        return 1

    reason = _gate_holiday(_today())
    if reason:
        print(f"tradeloop_route=SKIP reason={reason}")
        return 0
    reason = _gate_kill_switch(root)
    if reason:
        print(f"tradeloop_route=HALT reason={reason}")
        return 0
    if live_enabled() and not live_promotion_ready(root, settings):
        print("tradeloop_route=LIVE_NOT_READY")
        return 2

    with _global_lock(root) as acquired:
        if not acquired:
            print("tradeloop_route=LOCKED")
            return 0
        book_path = root / "state" / "ledger.db"
        led = Ledger(book_path)
        try:
            led.verify_chain()
        except LedgerTamperError:
            print("tradeloop_route=LEDGER_TAMPERED")
            return 1
        book = hydrate(book_path, settings.paper_starting_inr)
        pre_fills = len(book.fills)  # replayed history; anything past this is new
        try:
            routed = route_orders_file(orders_path, fills_path, book, settings, root=root, ledger=led)
        except Exception as exc:  # malformed orders.json -> loud abort, no routing
            fills_path.write_text(json.dumps({"error": "ORDERS_INVALID", "detail": str(exc)}), encoding="utf-8")
            print("tradeloop_route=ORDERS_INVALID")
            return 1
        # Persist this cycle's FILLED fills — the whole point of the book.
        # Without this append, positions would not survive to the next cycle.
        new_fills = [f for f in book.fills[pre_fills:] if f.status == "FILLED"]
        if new_fills:
            stops = {o.ticker.strip().upper(): float(o.hard_stop)
                     for o in load_orders(orders_path).orders if o.hard_stop is not None}
            append_book(book_path, new_fills, hard_stops=stops)
        filled = sum(1 for r in routed if r.status == "FILLED")
        rejected = sum(1 for r in routed if r.status == "RISK_REJECTED")
        print(f"tradeloop_route=OK orders={len(routed)} filled={filled} rejected={rejected}")
        return 0


def _prepare_takes_root() -> bool:
    import inspect
    return "root" in inspect.signature(_prepare).parameters


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="tradeloop.orchestrator")
    parser.add_argument("mode", choices=["premarket", "intraday", "postclose", "adhoc", "route"])
    parser.add_argument("run_dir", nargs="?", default=None,
                        help="run directory to approve+route (route mode only)")
    parser.add_argument("--request", default="")
    parser.add_argument("--backend", choices=["openrouter", "claude"], default=None,
                        help="reasoning backend; falls back to TRADELOOP_BACKEND env, then openrouter")
    parser.add_argument("--root", default=None,
                        help="tradeloop root override (isolated e2e tests / alt deployments)")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else ROOT
    if args.mode == "route":
        if not args.run_dir:
            parser.error("route requires a run_dir (the proposed cycle to approve)")
        return route_cycle(Path(args.run_dir), root=root)
    return run_cycle(args.mode, args.request, root=root, backend=args.backend)


if __name__ == "__main__":
    raise SystemExit(main())
