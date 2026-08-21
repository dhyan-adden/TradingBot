"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import dataclasses
import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import cast

from tradeloop.lib.audit import controls, reconcile
from tradeloop.lib.audit.ledger import ORDER_FILLED, STOP_UPDATED, Ledger, LedgerTamperError
from tradeloop.lib.approval import requires_live_human_approval, validate_approval
from tradeloop.lib.audit.postclose import run_postclose_learning
from tradeloop.lib.broker.orders_schema import load_orders
from tradeloop.lib.broker.paper_book import append as append_book, hydrate
from tradeloop.lib.broker.live_state import live_reconcile_allows_route, refresh_live_reconciliation
from tradeloop.lib.broker.router import live_enabled, live_promotion_ready, route_orders_file
from tradeloop.lib.config import load_settings, risk_caps
from tradeloop.lib.data.evidence import uncited_news_candidates, validate_evidence
from tradeloop.lib.data.grounding import load_scan_levels, validate_grounding
from tradeloop.lib.data.snapshot import load_snapshot
from tradeloop.lib.data.ticker_master import load_ticker_master
from tradeloop.lib.llm import stages
from tradeloop.lib.llm.claude_client import ClaudeStageClient
from tradeloop.lib.llm.quality import quality_has_hard_block_new_buys
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.opencode_client import OpenCodeStageClient
from tradeloop.lib.llm.schemas import AdhocIntake, HoldingsReview, Order, PMDecision, TradePlan
from tradeloop.lib.risk.checks import RiskState
from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.lib.risk.sizing import apply_guardrails, position_size_from_stop
from tradeloop.lib.util.holidays import is_nse_holiday
from tradeloop.lib.util.ist_clock import IST
from tradeloop.scripts.prepare_cycle import _portfolio_state, prepare as _prepare

ROOT = Path(__file__).resolve().parent

# Non-order modes (everything but premarket/adhoc) run a holdings-focused DAG:
# no discovery (shortlist/debate) and no trader/risk/PM order stages, ending in
# the holdings review. Intraday is a cheap pulse (news delta + chart health);
# postclose re-underwrites the book with sentiment + fundamentals too. The
# router's _sides_for_mode stays the hard order-policy enforcement at route time.
_MODE_DAGS = {
    "intraday": ["10_news", "13_technical", "15_holdings_review"],
    "postclose": ["10_news", "11_sentiment", "12_fundamentals",
                  "13_technical", "15_holdings_review"],
}


def _dag_for_mode(mode: str) -> list[str]:
    return list(_MODE_DAGS.get(mode, stages.DAG))


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


def _load_holdings_ltps(run_dir: Path) -> dict[str, float]:
    ltp_path = run_dir / "holdings_ltp.json"
    if not ltp_path.exists():
        return {}
    raw = json.loads(ltp_path.read_text(encoding="utf-8"))
    source = raw.get("ltps", raw) if isinstance(raw, dict) else {}
    return {k.strip().upper(): float(v) for k, v in source.items()}


def _holdings_actions(run_dir: Path, mode: str, root: Path) -> tuple[list[Order], dict[str, float]]:
    """Deterministic money-path derivation from the holdings review. Intraday
    ADD verdicts become top-up BUY orders, EXIT/TRIM verdicts become SELL orders
    priced at the snapshotted LTP;
    TIGHTEN_STOP verdicts become tighten-only stop updates (applied at route
    time, both modes). A held symbol whose LTP is at/below its recorded stop is
    force-exited even if the review missed it: the stop was approved when the
    position opened, so enforcing it is not a new decision. Postclose produces
    no orders ever - the market is closed and a paper fill would be fiction."""
    review = HoldingsReview.model_validate_json(
        (run_dir / "15_holdings_review.json").read_text(encoding="utf-8"))
    ltps = _load_holdings_ltps(run_dir)
    state = _portfolio_state(root)
    positions, stops = state.positions, state.hard_stops
    reviewed = {r.ticker.strip().upper(): r for r in review.reviews}
    settings = load_settings(root / "config" / "settings.yaml")

    orders: list[Order] = []
    if mode == "intraday":
        for sym, r in reviewed.items():
            qty, ltp = positions.get(sym, 0), ltps.get(sym)
            if r.verdict == "ADD" and qty > 0 and ltp:
                stop = float(r.new_stop or stops.get(sym, 0.0))
                target_qty = _deterministic_qty(ltp, stop, settings) if stop > 0 else 0
                add_qty = max(0, target_qty - qty)
                if add_qty > 0:
                    orders.append(Order(ticker=sym, side="BUY", quantity=add_qty, price=ltp,
                                        hard_stop=stop, strategy_family="position_management",
                                        reason=f"add:{r.reason_code}"))
                continue
            if r.verdict not in ("EXIT", "TRIM") or qty <= 0 or not ltp:
                continue  # no price or no position -> nothing routable
            sell_qty = qty if r.verdict == "EXIT" else min(r.exit_quantity or 0, qty)
            if sell_qty <= 0:
                continue
            orders.append(Order(ticker=sym, side="SELL", quantity=sell_qty, price=ltp,
                                strategy_family="position_management",
                                reason=f"{r.verdict.lower()}:{r.reason_code}"))
        ordered = {o.ticker for o in orders}
        for sym, qty in positions.items():
            stop, ltp = stops.get(sym, 0.0), ltps.get(sym)
            if qty > 0 and stop > 0 and ltp and ltp <= stop and sym not in ordered:
                orders.append(Order(ticker=sym, side="SELL", quantity=qty, price=ltp,
                                    strategy_family="position_management",
                                    reason="exit:stop_breach_enforced"))

    stop_updates: dict[str, float] = {}
    for sym, r in reviewed.items():
        if (r.verdict == "TIGHTEN_STOP" and r.new_stop
                and positions.get(sym, 0) > 0 and r.new_stop > stops.get(sym, 0.0)):
            stop_updates[sym] = float(r.new_stop)
    return orders, stop_updates


def _stage_done(run_dir: Path, name: str) -> bool:
    """Resume guard: a stage whose validated .json artifact already exists is
    not re-run, so completing an interrupted run never re-pays for finished
    model calls. A half-written artifact fails validation and re-runs."""
    path = run_dir / f"{name}.json"
    if not path.exists():
        return False
    try:
        stages.SCHEMA_FOR_STAGE[name].model_validate_json(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


_CF_START = "<!-- auto:holdings_review:start -->"
_CF_END = "<!-- auto:holdings_review:end -->"


def _write_carry_forward(memory_root: Path, run_id: str, review: HoldingsReview) -> None:
    """Replace the single auto holdings-review block in carry_forward_context.md.
    prepare_cycle injects this file into every 00_context, so this is the wire
    that makes a postclose verdict actionable at the next premarket. Manual
    notes outside the markers are never touched; the block is replaced, not
    appended, so the context cannot grow without bound."""
    path = memory_root / "carry_forward_context.md"
    lines = [f"### Holdings review ({run_id})", ""]
    for r in review.reviews:
        extra = ""
        if r.verdict == "TIGHTEN_STOP" and r.new_stop:
            extra = f" new_stop={r.new_stop}"
        if r.verdict == "TRIM" and r.exit_quantity:
            extra = f" exit_quantity={r.exit_quantity}"
        lines.append(f"- {r.ticker}: {r.verdict} ({r.reason_code}, "
                     f"conviction {r.conviction}){extra} - {r.rationale}")
    if review.carry_forward.strip():
        lines += ["", review.carry_forward.strip()]
    block = "\n".join([_CF_START, *lines, _CF_END])
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if _CF_START in text and _CF_END in text:
        pre, rest = text.split(_CF_START, 1)
        _, post = rest.split(_CF_END, 1)
        text = pre + block + post
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    path.write_text(text, encoding="utf-8")


def _run_reasoning(run_dir: Path, mode: str, backend: str, timeout: int,
                   client=None, settings=None, root: Path | None = None) -> int:
    """Dispatch reasoning to the selected backend's client, then run the one
    deterministic DAG. Both backends write a schema-valid orders.json; the route
    phase validates + gates it identically, so risk controls are backend-independent.

    - "openrouter" -> LLMClient (httpx -> OpenRouter): dormant fallback.
    - "claude"     -> ClaudeStageClient (claude -p per stage on your subscription).
    - "opencode"   -> OpenCodeStageClient (OpenAI subscription + OpenRouter models).

    Returns match P0's contract: -1 on cycle-timeout, 0 on success, nonzero on failure.
    """
    backend = (backend or "openrouter").lower()
    if backend not in ("openrouter", "claude", "opencode"):
        raise ValueError(
            f"unknown reasoning backend {backend!r} (use claude|opencode|openrouter)")
    if client is None:
        if backend == "claude":
            client = ClaudeStageClient(audit_path=run_dir / "llm_calls.jsonl")
        elif backend == "opencode":
            client = OpenCodeStageClient(audit_path=run_dir / "llm_calls.jsonl")
        else:
            client = LLMClient(audit_path=run_dir / "llm_calls.jsonl")
    generated_by = {
        "claude": "tradeloop.reasoning.claude",
        "opencode": "tradeloop.reasoning.opencode",
    }.get(backend, "tradeloop.reasoning.p1")
    return _run_reasoning_dag(run_dir, mode, timeout, client, settings, generated_by, root)


def _run_reasoning_dag(run_dir: Path, mode: str, timeout: int, client,
                       settings=None, generated_by: str = "tradeloop.reasoning.p1",
                       root: Path | None = None) -> int:
    """Deterministic DAG: each stage returns a validated pydantic form written to
    run_dir/<stage>.json; Python - not the LLM - then serialises orders.json from
    the validated PMDecision. Client-agnostic: OpenRouter or Claude behind the same
    loop (route_orders_file reads the OrdersFile shape and runs evaluate() on every order)."""
    deadline = time.monotonic() + timeout  # bound the DAG exactly as P0's subprocess timeout= did

    dag = _dag_for_mode(mode)
    if mode == "adhoc" and (run_dir / "user_request.md").exists():
        if time.monotonic() > deadline:
            return -1
        try:
            if _stage_done(run_dir, "05_adhoc_intake"):  # resume: keep the paid-for intake
                intake = AdhocIntake.model_validate_json(
                    (run_dir / "05_adhoc_intake.json").read_text(encoding="utf-8"))
            else:
                intake = cast(AdhocIntake, stages.run_stage(
                    "05_adhoc_intake", run_dir, client, settings=settings))
        except Exception as exc:  # same record-loudly contract as the DAG loop:
            # a bad intake must fail the cycle, not crash out or prune it hollow
            (run_dir / "reasoning_error.txt").write_text(
                f"reasoning failed at 05_adhoc_intake: {exc}\n", encoding="utf-8")
            return -2
        wanted = {s.removesuffix(".md") for s in intake.required_stages}
        if wanted:
            dag = [s for s in dag if s in wanted]

    for name in dag:
        if time.monotonic() > deadline:
            return -1
        try:
            if not _stage_done(run_dir, name):
                stages.run_stage(name, run_dir, client, settings=settings)
            if name == "30_trade_plan" and settings is not None:
                _size_trade_plan(run_dir, settings)  # deterministic qty, not the LLM's guess; idempotent on resume
        except Exception as exc:  # a stage that can't produce valid output must not
            # crash mid-cycle and leave a partial run that looks like a clean "hold".
            # Record it loudly and fail the cycle; run_cycle -> REASONING_FAILED.
            (run_dir / "reasoning_error.txt").write_text(
                f"reasoning failed at {name}: {exc}\n", encoding="utf-8")
            return -2

    if "41_pm_decision" in dag:
        pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
        orders, held = pm.orders, pm.held
    elif "15_holdings_review" in dag:
        orders, stop_updates = _holdings_actions(run_dir, mode,
                                                 root or run_dir.parent.parent)
        held = []
        (run_dir / "stop_updates.json").write_text(
            json.dumps(stop_updates, indent=2), encoding="utf-8")
    else:  # research-only adhoc: no PM stage ran, so there is nothing to route
        orders, held = [], []
    orders_file = {
        "mode": mode,
        "live_orders_enabled": False,      # paper default; live only past promotion gate
        "generated_by": generated_by,
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
              backend: str | None = None, run_dir: Path | None = None) -> int:
    """Propose phase of the split cycle: gates -> reason -> validated orders.json,
    then STOP. Nothing routes until route_cycle(run_dir) is invoked - that
    invocation is the approval (a human/overseer reviewed the orders first).

    run_dir resumes an interrupted run in place: prepare is skipped and stages
    with validated artifacts are not re-billed (see _stage_done)."""
    settings = load_settings(root / "config" / "settings.yaml")
    backend = backend or os.getenv("TRADELOOP_BACKEND", "openrouter")

    if run_dir is not None and not Path(run_dir).name.endswith(f"_{mode}"):
        # the run dir's trailing token drives route-time policy; a mismatch would
        # let a postclose artifact set route under premarket order rules
        print(f"tradeloop_cycle=RUN_DIR_MODE_MISMATCH run_dir={run_dir} mode={mode}")
        return 2

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
    if mode in _MODE_DAGS and not _portfolio_state(root).positions:
        # Holdings-focused modes have nothing to review on an empty book; skip
        # before prepare/scan/LLM so it costs zero tokens. Premarket owns
        # new-entry discovery and is never gated on holdings.
        print("tradeloop_cycle=SKIP reason=no_holdings")
        return 0

    with _global_lock(root) as acquired:
        if not acquired:
            print("tradeloop_cycle=LOCKED")
            return 0
        if run_dir is not None:  # resume in place: never re-prepare (and re-bill) a paid-for run
            run_dir = Path(run_dir)
        else:
            run_dir = _prepare(mode, request, root=root) if _prepare_takes_root() else _prepare(mode, request)
        rc = _run_reasoning(run_dir, mode, backend, settings.cycle_timeout_seconds,
                            settings=settings, root=root)
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

        review_path = run_dir / "15_holdings_review.json"
        if review_path.exists():
            try:
                _write_carry_forward(root / "memory", run_dir.name,
                                     HoldingsReview.model_validate_json(
                                         review_path.read_text(encoding="utf-8")))
            except Exception as exc:  # analysis plumbing must not fail the cycle
                (run_dir / "carry_forward_error.txt").write_text(
                    f"carry-forward write failed: {exc}\n", encoding="utf-8")

        snap = load_snapshot(run_dir)
        if snap is not None:
            ev = validate_evidence(run_dir, snap)
            if not ev.ok:
                print(f"tradeloop_cycle=EVIDENCE_INVALID missing={len(ev.missing)} run_dir={run_dir}")
                return 1

        # Heuristic tripwire (warn, never block): news-track shortlist names
        # with zero citations anywhere means the citation chain may have gone
        # silent - a shape the evidence gate above cannot see.
        suspect = uncited_news_candidates(run_dir)
        if suspect:
            print(f"tradeloop_warning=UNCITED_NEWS_CANDIDATES tickers={','.join(suspect)} run_dir={run_dir}")

        # Price grounding: entry/hard_stop must match the frozen scanner levels,
        # not numbers the model invented from a news headline. Skipped when the
        # scan is dormant (no setups frozen), same policy as the evidence gate.
        scan_levels = load_scan_levels(run_dir)
        if scan_levels:
            gr = validate_grounding(orders, scan_levels)
            if not gr.ok:
                print(f"tradeloop_cycle=PRICE_UNGROUNDED violations={len(gr.violations)} run_dir={run_dir}")
                return 1

        # Quality gate: a hard_block/new_buys quality line forbids any NEW BUY.
        # SELL-only exit orders are still allowed (risk-managed unwinds), so a
        # degraded research stage can never silently become a confident entry.
        if quality_has_hard_block_new_buys(run_dir):
            has_buy = any(str(o.side).upper() == "BUY" for o in orders)
            if has_buy:
                (run_dir / "quality_block.json").write_text(json.dumps({
                    "reason": "hard_block/new_buys quality line present; BUY orders forbidden",
                    "orders": n_orders,
                }, indent=2), encoding="utf-8")
                print(f"tradeloop_cycle=QUALITY_BLOCKED run_dir={run_dir}")
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
    # Auto mode must not live-route unless the operator explicitly enabled
    # allow_auto_live; otherwise the policy engine is not in force and skipping
    # human approval would be unsafe. Human-in-loop is unaffected.
    if live_enabled() and settings.approval_mode == "auto" and not settings.allow_auto_live:
        print("tradeloop_route=AUTO_LIVE_DISABLED")
        return 2
    # Live human-in-loop: the run must carry an approval artifact bound to the
    # exact orders.json. Auto mode skips this (it relies on the stricter policy
    # gate instead) and must never reuse a stale human approval.
    if live_enabled() and requires_live_human_approval(settings):
        approval = validate_approval(run_dir, orders_path)
        if not approval.ok:
            print(f"tradeloop_route=APPROVAL_REQUIRED reasons={approval.reasons}")
            return 2
    # Live route must reflect real broker state: refresh a fresh reconciliation
    # (read-only Zerodha snapshot -> deterministic check) before payloads. Paper
    # routes never consult the broker snapshot.
    if live_enabled():
        refresh_live_reconciliation(run_dir, root, orders_path)
        if not live_reconcile_allows_route(run_dir):
            print("tradeloop_route=LIVE_RECONCILE_BLOCKED")
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
        # Cycle mode drives the route-time trade policy (postclose routes nothing,
        # intraday exits only). prepare_cycle names run dirs `<ts>_<mode>`, so the
        # trailing token is the authoritative mode regardless of backend.
        cycle_mode = run_dir.name.rsplit("_", 1)[-1]
        try:
            routed = route_orders_file(orders_path, fills_path, book, settings, root=root, ledger=led, mode=cycle_mode,
                                       live_route_authorized=live_enabled())
        except Exception as exc:  # malformed orders.json -> loud abort, no routing
            fills_path.write_text(json.dumps({"error": "ORDERS_INVALID", "detail": str(exc)}), encoding="utf-8")
            print("tradeloop_route=ORDERS_INVALID")
            return 1
        # Persist this cycle's FILLED fills — the whole point of the book.
        # Without this append, positions would not survive to the next cycle.
        new_fills = [f for f in book.fills[pre_fills:] if f.status == "FILLED"]
        if new_fills:
            approved = load_orders(orders_path).orders
            stops = {o.ticker.strip().upper(): float(o.hard_stop)
                     for o in approved if o.hard_stop is not None}
            # Entry plan (target, strategy) rides the BUY fill event so attribution
            # can score the round trip whichever future run closes it.
            plan_meta = {o.ticker.strip().upper():
                         {"target_1": o.target_1, "strategy_family": o.strategy_family}
                         for o in approved if o.side.strip().upper() == "BUY"}
            append_book(book_path, new_fills, hard_stops=stops, plan_meta=plan_meta)
        # Stop updates ride the same approval as the orders (invoking route IS
        # the approval). Tighten-only and held-only are re-checked here against
        # the live post-fill book, so a full exit cancels its own stale tighten.
        # Postclose may tighten stops (pure risk reduction, no fill involved)
        # even though it can never fill an order.
        stops_applied = 0
        stop_path = run_dir / "stop_updates.json"
        if stop_path.exists():
            try:
                updates = {str(k).strip().upper(): float(v) for k, v in
                           json.loads(stop_path.read_text(encoding="utf-8")).items()}
            except (ValueError, TypeError):
                updates = {}
            current: dict[str, float] = {}
            for event in led.replay([ORDER_FILLED, STOP_UPDATED]):
                if float(event.get("hard_stop", 0.0)) > 0:
                    current[event["symbol"]] = float(event["hard_stop"])
            for sym, new_stop in sorted(updates.items()):
                if book.positions.get(sym, 0) > 0 and new_stop > current.get(sym, 0.0):
                    led.append({"type": STOP_UPDATED, "symbol": sym, "hard_stop": new_stop})
                    stops_applied += 1
        filled = sum(1 for r in routed if r.status == "FILLED")
        rejected = sum(1 for r in routed if r.status == "RISK_REJECTED")
        mode_blocked = sum(1 for r in routed if r.status == "MODE_DISALLOWED")
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
        print(f"tradeloop_route=OK orders={len(routed)} filled={filled} rejected={rejected} "
              f"mode_blocked={mode_blocked} stops_tightened={stops_applied}")
        return 0


def _prepare_takes_root() -> bool:
    import inspect
    return "root" in inspect.signature(_prepare).parameters


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="tradeloop.orchestrator")
    parser.add_argument("mode", choices=["premarket", "intraday", "postclose", "adhoc", "route"])
    parser.add_argument("run_dir", nargs="?", default=None,
                        help="route mode: run directory to approve+route. Other modes: "
                             "resume this interrupted run in place (completed stages are "
                             "not re-billed)")
    parser.add_argument("--request", default="")
    parser.add_argument("--backend", choices=["openrouter", "claude", "opencode"], default=None,
                        help="reasoning backend; falls back to TRADELOOP_BACKEND env, then openrouter")
    parser.add_argument("--root", default=None,
                        help="tradeloop root override (isolated e2e tests / alt deployments)")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else ROOT
    if args.mode == "route":
        if not args.run_dir:
            parser.error("route requires a run_dir (the proposed cycle to approve)")
        return route_cycle(Path(args.run_dir), root=root)
    return run_cycle(args.mode, args.request, root=root, backend=args.backend,
                     run_dir=Path(args.run_dir) if args.run_dir else None)


if __name__ == "__main__":
    raise SystemExit(main())
