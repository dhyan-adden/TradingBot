"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import fcntl
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.broker.paper_book import append as append_book, hydrate
from tradeloop.lib.broker.router import live_enabled, live_promotion_ready, route_orders_file
from tradeloop.lib.config import load_settings
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


def _run_reasoning(run_dir: Path, mode: str, agent: str, timeout: int, client=None) -> int:
    """P1: run the 13-role DAG in-process (was: exec external codex/claude CLI).

    Signature preserves P0's positional (run_dir, mode, agent, timeout): run_cycle
    still calls _run_reasoning(run_dir, mode, agent, settings.cycle_timeout_seconds)
    unchanged. `agent` is now unused (no external CLI) but kept for compat.

    Each stage returns a validated pydantic form written to run_dir/<stage>.json.
    Python - not the LLM - then serialises orders.json from the validated
    PMDecision, preserving the P0 order-path contract (route_orders_file reads
    the OrdersFile object shape and runs evaluate() on every order).

    Returns an int exit code matching P0's contract: -1 on cycle-timeout
    (run_cycle -> TIMEOUT, exit 1), 0 on success.
    """
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

    pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
    orders_file = {
        "mode": mode,
        "live_orders_enabled": False,      # paper default; live only past promotion gate
        "generated_by": "tradeloop.reasoning.p1",
        "orders": [o.model_dump() for o in pm.orders],
        "held": [o.model_dump() for o in pm.held],
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
              agent: str | None = None) -> int:
    settings = load_settings(root / "config" / "settings.yaml")
    agent = agent or os.getenv("TRADELOOP_AGENT", "codex")

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
        rc = _run_reasoning(run_dir, mode, agent, settings.cycle_timeout_seconds)
        if rc == -1:
            print("tradeloop_cycle=TIMEOUT")
            return 1
        if rc != 0:
            print(f"tradeloop_cycle=REASONING_FAILED rc={rc}")
            return 1

        orders_path = run_dir / "orders.json"
        fills_path = run_dir / "fills.json"
        book_path = root / "state" / "paper_book.jsonl"
        book = hydrate(book_path, settings.paper_starting_inr)
        pre_fills = len(book.fills)  # replayed history; anything past this is new
        try:
            routed = route_orders_file(orders_path, fills_path, book, settings, root=root)
        except Exception as exc:  # malformed orders.json -> loud abort, no routing
            fills_path.write_text(json.dumps({"error": "ORDERS_INVALID", "detail": str(exc)}), encoding="utf-8")
            print("tradeloop_cycle=ORDERS_INVALID")
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
        print(f"tradeloop_cycle=OK mode={mode} orders={len(routed)} filled={filled} rejected={rejected}")
        return 0


def _prepare_takes_root() -> bool:
    import inspect
    return "root" in inspect.signature(_prepare).parameters


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="tradeloop.orchestrator")
    parser.add_argument("mode", choices=["premarket", "intraday", "postclose", "adhoc"])
    parser.add_argument("--request", default="")
    args = parser.parse_args(argv)
    return run_cycle(args.mode, args.request)


if __name__ == "__main__":
    raise SystemExit(main())
