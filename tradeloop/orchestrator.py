"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import dataclasses
import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from tradeloop.lib.audit import controls, reconcile
from tradeloop.lib.audit.ledger import ORDER_FILLED, Ledger, LedgerTamperError
from tradeloop.lib.audit.postclose import run_postclose_learning
from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.broker.paper_book import append as append_book, hydrate
from tradeloop.lib.broker.router import live_enabled, live_promotion_ready, route_orders_file
from tradeloop.lib.config import load_settings, risk_caps
from tradeloop.lib.data.evidence import validate_evidence
from tradeloop.lib.data.grounding import load_scan_levels, validate_grounding
from tradeloop.lib.data.snapshot import load_snapshot
from tradeloop.lib.data.ticker_master import load_ticker_master
from tradeloop.lib.llm import stages
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.schemas import PMDecision, TradePlan
from tradeloop.lib.risk.checks import RiskState
from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.risk.sizing import apply_guardrails, position_size_from_stop
from tradeloop.lib.util.holidays import is_nse_holiday
from tradeloop.lib.util.ist_clock import IST
from tradeloop.scripts.prepare_cycle import prepare as _prepare

ROOT = Path(__file__).resolve().parent


def _gate_holiday(today: date) -> str | None:
    return "nse_holiday" if is_nse_holiday(today) else None


def _already_routed(fills_path: Path) -> bool:
    """True only when fills.json holds real routed content. prepare_cycle
    pre-creates an empty [] placeholder (the postclose 50_post_trade input);
    that empty file must NOT count as already-routed, or the approve step could
    never run. A non-empty or unparseable fills file means routing already
    happened - block the re-route."""
    if not fills_path.exists():
        return False
    try:
        return bool(json.loads(fills_path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return True


def _gate_kill_switch(root: Path) -> str | None:
    return "kill_switch" if kill_switch_active(root) else None


def _today() -> date:
    return date.today()


def _deterministic_qty(entry: float, hard_stop: float, settings) -> int:
    """Authoritative share count from the risk budget + guardrails. The LLM
    trader is reliable on thesis/entry/stop but routinely lowballs quantity: a
    green-lit ICICI came in at 4 shares (~Rs 5.7k, 0.14% risk) against the ~17
    the 1.5% budget permits, then got vetoed under the 15k min-position floor.
    Sizing is a formula, not an LLM guess. Returns 0 when untradeable (can't
    clear the min-position floor), matching the route-gate's own reject rule."""
    raw = position_size_from_stop(
        settings.paper_starting_inr, entry, hard_stop,
        atr_value=0.0, per_trade_risk_pct=settings.per_trade_risk_pct)
    return apply_guardrails(
        raw, entry, settings.paper_starting_inr, settings.max_position_pct,
        adv20_inr=None, min_position_size_inr=settings.min_position_size_inr)


def _size_trade_plan(run_dir: Path, settings) -> None:
    """Overwrite each ticket's quantity with the deterministic size and drop
    tickets that can't clear the floor. Runs immediately after the trader stage
    so the risk manager and PM reason about correctly-sized tickets - otherwise
    a lowballed qty gets vetoed downstream and no good trade ever routes."""
    path = run_dir / "30_trade_plan.json"
    if not path.exists():
        return
    plan = TradePlan.model_validate_json(path.read_text(encoding="utf-8"))
    sized = [t.model_copy(update={"quantity": q})
             for t in plan.tickets
             if (q := _deterministic_qty(t.entry, t.hard_stop, settings)) > 0]
    plan = plan.model_copy(update={"tickets": sized})
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "30_trade_plan.md").write_text(
        f"# 30_trade_plan\n\n```json\n{plan.model_dump_json(indent=2)}\n```\n",
        encoding="utf-8")


def _run_reasoning(run_dir: Path, mode: str, backend: str, timeout: int,
                   client=None, settings=None) -> int:
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
        return _run_reasoning_openrouter(run_dir, mode, timeout, client, settings)
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


def _run_reasoning_openrouter(run_dir: Path, mode: str, timeout: int,
                              client=None, settings=None) -> int:
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
        try:
            stages.run_stage(name, run_dir, client)
            if name == "30_trade_plan" and settings is not None:
                _size_trade_plan(run_dir, settings)  # deterministic qty, not the LLM's guess
        except Exception as exc:  # a stage that can't produce valid output must not
            # crash mid-cycle and leave a partial run that looks like a clean "hold".
            # Record it loudly and fail the cycle; run_cycle -> REASONING_FAILED.
            (run_dir / "reasoning_error.txt").write_text(
                f"reasoning failed at {name}: {exc}\n", encoding="utf-8")
            return -2

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
        rc = _run_reasoning(run_dir, mode, backend, settings.cycle_timeout_seconds,
                            settings=settings)
        if rc == -1:
            print("tradeloop_cycle=TIMEOUT")
            return 1
        if rc != 0:
            print(f"tradeloop_cycle=REASONING_FAILED rc={rc}")
            return 1

        # Validate now so a bad orders.json fails loudly at propose time, not
        # at approval time.
        try:
            orders = load_orders(run_dir / "orders.json").orders
            n_orders = len(orders)
        except Exception:
            print("tradeloop_cycle=ORDERS_INVALID")
            return 1

        snap = load_snapshot(run_dir)
        if snap is not None:
            ev = validate_evidence(run_dir, snap)
            if not ev.ok:
                print(f"tradeloop_cycle=EVIDENCE_INVALID missing={len(ev.missing)} run_dir={run_dir}")
                return 1

        # Price grounding: entry/hard_stop must match the frozen scanner levels,
        # not numbers the model invented from a news headline. Skipped when the
        # scan is dormant (no setups frozen), same policy as the evidence gate.
        scan_levels = load_scan_levels(run_dir)
        if scan_levels:
            gr = validate_grounding(orders, scan_levels)
            if not gr.ok:
                print(f"tradeloop_cycle=PRICE_UNGROUNDED violations={len(gr.violations)} run_dir={run_dir}")
                return 1

        print(f"tradeloop_cycle=AWAITING_APPROVAL mode={mode} orders={n_orders} run_dir={run_dir}")
        return 0


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _run_postclose_audit(run_dir: Path, root: Path, memory_root: Path,
                         run_id: str, timestamp: str, live_ready: bool = False):
    """Post-route accountability sweep: reconcile + controls + attribution + learning
    over the just-approved trade plus the full ledger. Fires from route_cycle (the
    approve phase) right after fills are persisted - in the propose/approve split that
    is the one moment orders.json + fills.json + the fresh ledger are all consistent
    (the plan's original 'postclose branch of run_cycle' predates the split; run_cycle
    never routes). Observability only: it writes artifacts and updates the learning
    memory, never routes, and the caller wraps it so it can never fail a committed route.

    Two fill shapes are used deliberately: reconcile/attribution/learning consume the
    LEDGER-fill dicts from ledger.replay([ORDER_FILLED]); controls consumes the
    ROUTING-OUTCOME dicts route_orders_file wrote to fills.json (that shape is what
    lets it flag a bad order recorded status=FILLED).

    The control re-check evaluates each order against the PRE-route book (this run's
    fills undone), reproducing the gate's actual pre-trade context. Re-checking against
    the post-fill book would double-count the just-routed position in the sector/total
    caps and falsely flag a legitimately-filled near-cap order as a gate leak (verified:
    HDFCBANK+SBIN at ~49% Financials would each re-eval at ~73%).
    ponytail: pre-route reconstruction is static, not incremental - a batch that
    collectively breaches a cap while each order is individually clean (and the gate
    rejected the later one) can still surface as a significant_deficiency; faithful
    per-order incremental replay is the upgrade if that case ever bites."""
    settings = load_settings(root / "config" / "settings.yaml")
    orders = load_orders(run_dir / "orders.json")

    ledger = Ledger(root / "state" / "ledger.db")
    book = hydrate(root / "state" / "ledger.db", settings.paper_starting_inr)
    ledger_fills = ledger.replay([ORDER_FILLED])  # {symbol,side,quantity,fill_price,status}

    records = load_ticker_master(root / "config" / "universe.yaml")
    universe = [r.symbol for r in records]
    sectors = {r.symbol.strip().upper(): r.sector for r in records}
    # equity basis (cash + deployed at cost) mirrors router._equity, so the control
    # re-derivation uses the same capital the live gate did - not post-fill cash alone.
    equity = book.cash_inr + sum(q * book.avg_prices.get(s, 0.0) for s, q in book.positions.items())
    caps = risk_caps(settings, universe, equity)

    # Pre-route book: undo THIS run's FILLED orders so each is re-evaluated against the
    # positions the gate actually saw before it routed (no self double-count).
    filled_syms = {str(f.get("payload", {}).get("symbol", "")).strip().upper()
                   for f in json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
                   if str(f.get("status", "")).upper() == "FILLED"}
    pre_positions, pre_avg = dict(book.positions), dict(book.avg_prices)
    for o in orders.orders:
        sym = o.ticker.strip().upper()
        if sym not in filled_syms:
            continue
        pre_positions[sym] = pre_positions.get(sym, 0) - (int(o.quantity) if o.side.upper() == "BUY" else -int(o.quantity))
        if pre_positions[sym] <= 0:
            pre_positions.pop(sym, None)
            pre_avg.pop(sym, None)
    state = RiskState(
        cash_inr=book.cash_inr, positions=pre_positions, avg_prices=pre_avg,
        sectors={**{s: sectors.get(s, "") for s in pre_positions},
                 **{o.ticker.strip().upper(): sectors.get(o.ticker.strip().upper(), "") for o in orders.orders}})

    # 1) reconcile positions across independent derivations (ledger-fill shape)
    deltas = reconcile.compare(book, ledger, kite_holdings=None, orders=orders)
    (run_dir / "40_reconcile.md").write_text(
        "# Reconciliation\n\n" + ("\n".join(
            f"- {d.symbol}: {d.field} {d.source_a}={d.value_a} vs {d.source_b}={d.value_b}"
            for d in deltas) or "- clean: all sources agree\n"),
        encoding="utf-8")

    # 2) controls: re-run the gate over the routing outcomes (fills.json shape)
    routed_fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    report = controls.recheck(orders, routed_fills, caps, state)
    (run_dir / "controls.json").write_text(
        json.dumps(dataclasses.asdict(report), indent=2), encoding="utf-8")

    # 3) learning loop: journal + dossiers + strategy_performance.md (Python-owned;
    #    it computes attribution internally over the ledger fills)
    return run_postclose_learning(run_dir, memory_root, ledger_fills,
                                  run_id=run_id, timestamp=timestamp, live_ready=live_ready)


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
    if _already_routed(fills_path):  # double-routing would double positions
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
        # Post-route accountability sweep (P4). Observability only, over the fills just
        # committed to the ledger - it must NEVER turn a good route into a failure, so a
        # throwing audit is recorded and the route still reports OK.
        try:
            # live_ready=False: the renderer must NOT stamp the manual "live_ready: true"
            # override from the gate's own result - that latches the gate permanently open
            # (the literal short-circuits live_promotion_ready). Promotion rides the earned
            # metric lines the render writes; the literal stays a human-only force switch.
            _run_postclose_audit(run_dir, root=root, memory_root=root / "memory",
                                 run_id=run_dir.name, timestamp=_now_iso(), live_ready=False)
        except Exception as exc:
            (run_dir / "audit_error.txt").write_text(f"postclose audit failed: {exc}\n", encoding="utf-8")
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
