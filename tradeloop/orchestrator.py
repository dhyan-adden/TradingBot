"""TradeLoop desk manager: gates -> lock -> prepare -> reason -> order path."""
import dataclasses
import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Sequence, cast

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
from tradeloop.lib.llm import routing, stages
from tradeloop.lib.llm.claude_client import ClaudeStageClient
from tradeloop.lib.llm.quality import quality_has_hard_block_new_buys
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.opencode_client import OpenCodeStageClient
from tradeloop.lib.llm.schemas import AdhocIntake, HoldingsReview, Order, PMDecision, TradePlan
from tradeloop.lib.memory.writer import append_manager_feedback
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

_MANAGER_BACKCHANNEL_INPUTS = (
    "manager_feedback.md",
    "41_pm_decision.md",
    "40_risk_report.md",
    "30_trade_plan.md",
    "03_market_regime.md",
    "analysis_quality.jsonl",
)

_FIXABLE_ROUTE_RISK_REASONS = {
    "max_position_allocation_exceeded",
    "max_total_deployed_exceeded",
    "max_open_positions_exceeded",
    "max_sector_allocation_exceeded",
}


def _dag_for_mode(mode: str) -> list[str]:
    return list(_MODE_DAGS.get(mode, stages.DAG))


def _generated_by_for_backend(backend: str) -> str:
    return {
        "claude": "tradeloop.reasoning.claude",
        "opencode": "tradeloop.reasoning.opencode",
    }.get((backend or "openrouter").lower(), "tradeloop.reasoning.p1")


def _backend_for_generated_by(generated_by: str | None) -> str:
    value = str(generated_by or "").lower()
    if ".opencode" in value:
        return "opencode"
    if ".claude" in value:
        return "claude"
    return "openrouter"


def _load_json_file(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _make_stage_client(backend: str, run_dir: Path):
    backend = (backend or "openrouter").lower()
    if backend == "claude":
        return ClaudeStageClient(audit_path=run_dir / "llm_calls.jsonl")
    if backend == "opencode":
        return OpenCodeStageClient(audit_path=run_dir / "llm_calls.jsonl")
    return LLMClient(audit_path=run_dir / "llm_calls.jsonl")


def _strongest_manager_model(backend: str) -> str:
    backend = (backend or "openrouter").lower()
    if backend == "claude":
        return routing.claude_model_for("41_pm_decision")
    if backend == "opencode":
        return routing.opencode_model_for("40_risk_report")
    return routing.model_for("41_pm_decision")


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


def _sorted_orders(orders: list[Order]) -> list[Order]:
    horizon: dict[str, int] = {
        "results_momentum": 5,
        "20d_breakout": 10,
        "post_earnings_drift": 15,
        "ema20_pullback": 20,
        "sector_rotation_leader": 20,
    }
    return sorted(
        orders,
        key=lambda o: horizon.get(str(o.strategy_family or "").lower(), 15),
    )


def _write_pm_outputs(run_dir: Path, pm: PMDecision, *, mode: str, generated_by: str) -> None:
    orders = _sorted_orders(list(pm.orders))
    held = list(pm.held)
    serialised = pm.model_copy(update={"orders": orders, "held": held})
    (run_dir / "41_pm_decision.json").write_text(
        serialised.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "41_pm_decision.md").write_text(
        f"# 41_pm_decision\n\n```json\n{serialised.model_dump_json(indent=2)}\n```\n",
        encoding="utf-8")
    _write_orders_file(run_dir, mode=mode, generated_by=generated_by, orders=orders, held=held)


def _write_orders_file(run_dir: Path, *, mode: str, generated_by: str,
                       orders: list[Order], held: list[Order]) -> None:
    orders = _sorted_orders(list(orders))
    held = list(held)
    orders_file = {
        "mode": mode,
        "live_orders_enabled": False,
        "generated_by": generated_by,
        "orders": [o.model_dump() for o in orders],
        "held": [o.model_dump() for o in held],
    }
    (run_dir / "orders.json").write_text(json.dumps(orders_file, indent=2), encoding="utf-8")


def _manager_backchannel_user(run_dir: Path, *, block_reason: str, threshold: float) -> str:
    summary = {
        "event": "conviction_gate_blocked",
        "threshold": threshold,
        "block_reason": block_reason,
        "instruction": (
            "Revise only with the supplied artifacts. Keep or drop BUY orders only if "
            "their ticker already exists in 30_trade_plan and already clears the "
            "threshold there. Never invent stronger conviction or new evidence."
        ),
    }
    parts = ["### block_summary.json", json.dumps(summary, indent=2)]
    for name in _MANAGER_BACKCHANNEL_INPUTS:
        path = run_dir / name
        if path.exists():
            parts.append(f"### {name}\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _write_manager_backchannel(run_dir: Path, payload: dict) -> None:
    (run_dir / "42_manager_backchannel.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Manager Backchannel",
        "",
        f"event: {payload.get('event', '')}",
        f"status: {payload.get('status', '')}",
        f"backend: {payload.get('backend', '')}",
        f"model: {payload.get('model', '')}",
        f"initial_block_reason: {payload.get('initial_block_reason', '')}",
    ]
    retry_reason = payload.get("retry_block_reason")
    if retry_reason:
        lines.append(f"retry_block_reason: {retry_reason}")
    error = payload.get("error")
    if error:
        lines.append(f"error: {error}")
    response = payload.get("manager_response")
    if response is not None:
        lines += ["", "```json", json.dumps(response, indent=2), "```"]
    (run_dir / "42_manager_backchannel.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _backchannel_snapshot(run_dir: Path) -> dict:
    raw = _load_json_file(run_dir / "42_manager_backchannel.json")
    return raw if isinstance(raw, dict) else {}


def _record_manager_feedback_entry(memory_root: Path, *, heading: str, body_lines: list[str],
                                   run_id: str, timestamp: str) -> None:
    append_manager_feedback(memory_root, heading, "\n".join(body_lines), run_id=run_id,
                            timestamp=timestamp)


def _record_conviction_block_feedback(memory_root: Path, run_dir: Path, orders: Sequence,
                                      *, threshold: float, reason: str, timestamp: str) -> None:
    backchannel = _backchannel_snapshot(run_dir)
    for idx, order in enumerate(orders, start=1):
        if str(order.side).upper() != "BUY":
            continue
        body = [
            "event: conviction_gate_blocked",
            f"symbol: {order.ticker.strip().upper()}",
            f"side: {order.side}",
            f"quantity: {order.quantity}",
            f"price: {order.price}",
            f"strategy_family: {order.strategy_family or ''}",
            f"threshold: {threshold}",
            f"reason: {reason}",
        ]
        if backchannel:
            body += [
                f"manager_retry_event: {backchannel.get('event', '')}",
                f"manager_retry_status: {backchannel.get('status', '')}",
                f"manager_retry_block_reason: {backchannel.get('retry_block_reason', '')}",
            ]
        _record_manager_feedback_entry(
            memory_root,
            heading=f"{run_dir.name} conviction-blocked {idx} {order.ticker.strip().upper()}",
            body_lines=body,
            run_id=run_dir.name,
            timestamp=timestamp,
        )


def _record_route_feedback(memory_root: Path, run_dir: Path, orders_file, routed, *, timestamp: str) -> None:
    by_symbol = {o.ticker.strip().upper(): o for o in orders_file.orders}
    backchannel = _backchannel_snapshot(run_dir)
    for idx, item in enumerate(routed, start=1):
        payload = getattr(item, "payload", {}) or {}
        symbol = str(payload.get("symbol", "")).strip().upper()
        order = by_symbol.get(symbol)
        reasons = payload.get("reasons", []) if isinstance(payload, dict) else []
        body = [
            "event: route_outcome",
            f"symbol: {symbol}",
            f"final_status: {getattr(item, 'status', '')}",
            f"routed_mode: {getattr(item, 'mode', '')}",
            f"side: {getattr(order, 'side', payload.get('side', '')) if order else payload.get('side', '')}",
            f"quantity: {getattr(order, 'quantity', payload.get('quantity', '')) if order else payload.get('quantity', '')}",
            f"price: {getattr(order, 'price', payload.get('fill_price', '')) if order else payload.get('fill_price', '')}",
            f"strategy_family: {getattr(order, 'strategy_family', '') if order else ''}",
            f"reasons: {', '.join(str(r) for r in reasons)}",
        ]
        if backchannel:
            body += [
                f"manager_retry_event: {backchannel.get('event', '')}",
                f"manager_retry_status: {backchannel.get('status', '')}",
                f"manager_retry_initial_reason: {backchannel.get('initial_block_reason', '')}",
                f"manager_retry_block_reason: {backchannel.get('retry_block_reason', '')}",
            ]
        _record_manager_feedback_entry(
            memory_root,
            heading=f"{run_dir.name} route-outcome {idx} {symbol or 'UNKNOWN'}",
            body_lines=body,
            run_id=run_dir.name,
            timestamp=timestamp,
        )


def _manager_backchannel_retry(run_dir: Path, *, mode: str, backend: str,
                               settings, client=None) -> tuple[bool, str | None]:
    orders_path = run_dir / "orders.json"
    orders_file = load_orders(orders_path)
    block_reason = _conviction_gate(run_dir, orders_file.orders, settings.auto_route_min_conviction)
    if not block_reason:
        return False, None

    model = _strongest_manager_model(backend)
    payload: dict[str, object] = {
        "event": "conviction_gate_blocked",
        "status": "attempted",
        "backend": backend,
        "model": model,
        "initial_block_reason": block_reason,
        "threshold": settings.auto_route_min_conviction,
    }
    try:
        client = client or _make_stage_client(backend, run_dir)
        system = (
            "You are the strongest bounded TradeLoop portfolio manager retry lane. "
            "You have no tools and no codebase access. Use only the supplied run "
            "artifacts. The previous PM decision failed the deterministic conviction "
            "gate. Return a PMDecision that is equally or more conservative than the "
            "current one. You may only keep BUY tickers that already exist in "
            "30_trade_plan and already meet the stated threshold there. You may drop "
            "orders, reduce size, or return no changes. Never invent new evidence, "
            "new tickers, or higher conviction."
        )
        user = _manager_backchannel_user(
            run_dir, block_reason=block_reason,
            threshold=settings.auto_route_min_conviction,
        )
        pm = cast(PMDecision, client.call_json(
            "41_pm_decision", system, user, PMDecision, model=model))
        retry_reason = _conviction_gate(run_dir, pm.orders, settings.auto_route_min_conviction)
        applied = bool(pm.orders) and not retry_reason
        payload.update({
            "status": "applied" if applied else "still_blocked",
            "retry_block_reason": retry_reason or "",
            "manager_response": pm.model_dump(),
        })
        if applied:
            generated_by = str((json.loads(orders_path.read_text(encoding="utf-8")) or {}).get("generated_by")
                               or _generated_by_for_backend(backend))
            if not generated_by.endswith(".manager_backchannel"):
                generated_by = f"{generated_by}.manager_backchannel"
            _write_pm_outputs(run_dir, pm, mode=mode, generated_by=generated_by)
        _write_manager_backchannel(run_dir, payload)
        return applied, retry_reason
    except Exception as exc:
        payload.update({"status": "error", "error": str(exc)})
        _write_manager_backchannel(run_dir, payload)
        return False, block_reason


def _route_reject_reason_map(routed) -> dict[str, list[str]]:
    rejected: dict[str, list[str]] = {}
    for item in routed:
        if str(getattr(item, "status", "")).upper() != "RISK_REJECTED":
            continue
        payload = getattr(item, "payload", {}) or {}
        symbol = str(payload.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        rejected[symbol] = [str(r) for r in payload.get("reasons", [])]
    return rejected


def _fixable_route_rejections(routed) -> dict[str, list[str]]:
    if any(str(getattr(item, "status", "")).upper() == "FILLED" for item in routed):
        return {}
    rejected = _route_reject_reason_map(routed)
    if not rejected:
        return {}
    if any(not reasons or any(r not in _FIXABLE_ROUTE_RISK_REASONS for r in reasons)
           for reasons in rejected.values()):
        return {}
    return rejected


def _manager_route_retry_user(run_dir: Path, rejected: dict[str, list[str]]) -> str:
    summary = {
        "event": "route_risk_rejected",
        "rejections": rejected,
        "instruction": (
            "Return a more conservative PMDecision. You may only keep or drop BUY orders "
            "already present in the current orders.json, and any kept BUY quantity must be "
            "less than or equal to the current quantity. Do not add tickers, change prices, "
            "or alter stops, targets, or side."
        ),
    }
    parts = ["### route_rejections.json", json.dumps(summary, indent=2)]
    for name in ("orders.json",) + _MANAGER_BACKCHANNEL_INPUTS:
        path = run_dir / name
        if path.exists():
            parts.append(f"### {name}\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _validate_conservative_route_retry(original_orders, revised_orders) -> str | None:
    original_by_symbol = {o.ticker.strip().upper(): o for o in original_orders}
    for revised in revised_orders:
        symbol = revised.ticker.strip().upper()
        original = original_by_symbol.get(symbol)
        if original is None:
            return f"new_order_not_allowed:{symbol}"
        if revised.side != "BUY" or original.side != "BUY":
            return f"only_existing_buy_orders_may_change:{symbol}"
        if int(revised.quantity) > int(original.quantity):
            return f"quantity_increase_not_allowed:{symbol}"
        if any([
            revised.product != original.product,
            float(revised.price or 0.0) != float(original.price or 0.0),
            str(revised.order_type) != str(original.order_type),
            float(revised.hard_stop or 0.0) != float(original.hard_stop or 0.0),
            float(revised.target_1 or 0.0) != float(original.target_1 or 0.0),
            float(revised.target_2 or 0.0) != float(original.target_2 or 0.0),
            float(revised.max_entry_price or 0.0) != float(original.max_entry_price or 0.0),
            str(revised.strategy_family or "") != str(original.strategy_family or ""),
        ]):
            return f"only_quantity_or_drop_allowed:{symbol}"
    return None


def _manager_route_rejection_retry(run_dir: Path, *, mode: str, generated_by: str,
                                   settings, rejected: dict[str, list[str]], client=None) -> tuple[bool, str | None]:
    orders_path = run_dir / "orders.json"
    current = load_orders(orders_path)
    backend = _backend_for_generated_by(generated_by)
    model = _strongest_manager_model(backend)
    payload: dict[str, object] = {
        "event": "route_risk_rejected",
        "status": "attempted",
        "backend": backend,
        "model": model,
        "initial_block_reason": json.dumps(rejected, sort_keys=True),
    }
    try:
        client = client or _make_stage_client(backend, run_dir)
        system = (
            "You are the strongest bounded TradeLoop risk-repair manager lane. "
            "You have no tools and no codebase access. Use only the supplied run artifacts. "
            "The deterministic route gate rejected the current BUY orders on allocation or cap "
            "limits. Return a PMDecision that is strictly more conservative: only drop current "
            "BUY orders or reduce their quantities. Do not add tickers, do not change price, "
            "stop, targets, side, product, or strategy family, and do not modify SELL orders."
        )
        user = _manager_route_retry_user(run_dir, rejected)
        pm = cast(PMDecision, client.call_json(
            "41_pm_decision", system, user, PMDecision, model=model))
        validation_error = _validate_conservative_route_retry(current.orders, pm.orders)
        payload["manager_response"] = pm.model_dump()
        if validation_error:
            payload.update({"status": "invalid_counter_request", "retry_block_reason": validation_error})
            _write_manager_backchannel(run_dir, payload)
            return False, validation_error
        retry_reason = _conviction_gate(run_dir, pm.orders, settings.auto_route_min_conviction)
        if retry_reason:
            payload.update({"status": "still_blocked", "retry_block_reason": retry_reason})
            _write_manager_backchannel(run_dir, payload)
            return False, retry_reason
        generated = str(current.generated_by or generated_by)
        if not generated.endswith(".manager_backchannel"):
            generated = f"{generated}.manager_backchannel"
        _write_pm_outputs(run_dir, pm, mode=mode, generated_by=generated)
        payload["status"] = "applied"
        _write_manager_backchannel(run_dir, payload)
        return True, None
    except Exception as exc:
        payload.update({"status": "error", "error": str(exc)})
        _write_manager_backchannel(run_dir, payload)
        return False, str(exc)


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


def _conviction_gate(run_dir: Path, orders: list, min_conviction: float) -> str | None:
    """Return a block reason string if any BUY order has conviction below threshold.
    Returns None when the gate passes (route is allowed). The trade plan is the
    conviction source because it carries per-ticket scores the PM stage flattens
    out. No plan file means no conviction data (intraday/postclose never write a
    trade plan); the gate passes so holdings-management cycles are never blocked."""
    plan_path = run_dir / "30_trade_plan.json"
    if not plan_path.exists():
        return None
    try:
        plan = TradePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return None  # malformed plan; route gate handles it
    buy_tickers = {str(o.ticker).strip().upper() for o in orders
                  if str(o.side).strip().upper() == "BUY"}
    if not buy_tickers:
        return None  # no BUY orders; gate does not apply
    conviction_map = {t.ticker.strip().upper(): t.conviction for t in plan.tickets}
    low = [(tk, conviction_map.get(tk, 0.0)) for tk in sorted(buy_tickers)
           if conviction_map.get(tk, 0.0) < min_conviction]
    if low:
        detail = " ".join(f"{t}={c:.1f}" for t, c in low)
        return f"conviction_below_threshold min={min_conviction} [{detail}]"
    return None


def _write_fills_summary(run_dir: Path, *, success: bool, n_orders: int,
                         reason: str = "") -> None:
    """Write a human-readable auto-route summary to fills_summary.md. This is
    the primary notification artifact for automated cycles (no human reviewer)."""
    lines = [
        "# Auto-Route Summary",
        "",
        f"run_dir: {run_dir.name}",
        f"timestamp: {_now_iso()}",
        f"orders_proposed: {n_orders}",
        f"result: {'ROUTED' if success else 'BLOCKED'}",
    ]
    if reason:
        lines.append(f"block_reason: {reason}")
    fills_path = run_dir / "fills.json"
    if success and fills_path.exists():
        try:
            fills = json.loads(fills_path.read_text(encoding="utf-8"))
            if isinstance(fills, list):
                filled = sum(1 for f in fills if f.get("status") == "FILLED")
                rejected = sum(1 for f in fills if f.get("status") == "RISK_REJECTED")
                lines += [f"fills_filled: {filled}", f"fills_risk_rejected: {rejected}"]
        except Exception:
            pass
    (run_dir / "fills_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gate(gate_id: str, label: str, status: str, detail: str,
          severity: str = "blocker") -> dict[str, str]:
    return {
        "id": gate_id,
        "label": label,
        "status": status,
        "severity": severity,
        "detail": detail,
    }


def _write_gate_summary(run_dir: Path, *, mode: str, phase: str, settings,
                        gates: list[dict[str, str]], summary: str) -> None:
    payload = {
        "run_dir": run_dir.name,
        "mode": mode,
        "phase": phase,
        "autonomy": {
            "approval_mode": settings.approval_mode,
            "paper_auto_route": settings.approval_mode == "auto" and not live_enabled(),
            "live_env_enabled": live_enabled(),
            "allow_auto_live": settings.allow_auto_live,
        },
        "gates": gates,
        "summary": summary,
        "updated_at": _now_iso(),
    }
    (run_dir / "gate_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")



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
        client = _make_stage_client(backend, run_dir)
    generated_by = _generated_by_for_backend(backend)
    return _run_reasoning_dag(run_dir, mode, timeout, client, settings, generated_by, root)


def _run_reasoning_dag(run_dir: Path, mode: str, timeout: int, client,
                       settings=None, generated_by: str = "tradeloop.reasoning.p1",
                       root: Path | None = None) -> int:
    """Deterministic DAG: each stage returns a validated pydantic form written to
    run_dir/<stage>.json; Python - not the LLM - then serialises orders.json from
    the validated PMDecision. Client-agnostic: OpenRouter or Claude behind the same
    loop (route_orders_file reads the OrdersFile shape and runs evaluate() on every order)."""
    deadline = time.monotonic() + timeout  # bound the DAG exactly as P0's subprocess timeout= did
    pm_result: PMDecision | None = None

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
        pm_result = pm
        orders, held = pm.orders, pm.held
    elif "15_holdings_review" in dag:
        orders, stop_updates = _holdings_actions(run_dir, mode,
                                                 root or run_dir.parent.parent)
        held = []
        (run_dir / "stop_updates.json").write_text(
            json.dumps(stop_updates, indent=2), encoding="utf-8")
    else:  # research-only adhoc: no PM stage ran, so there is nothing to route
        orders, held = [], []

    if "41_pm_decision" in dag:
        _write_pm_outputs(
            run_dir,
            (pm_result or PMDecision(orders=orders, held=held, evidence=[])).model_copy(
                update={"orders": orders, "held": held}),
            mode=mode,
            generated_by=generated_by,
        )
    else:
        _write_orders_file(run_dir, mode=mode, generated_by=generated_by,
                           orders=orders, held=held)
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
    live_active = live_enabled()

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
    if live_active and not live_promotion_ready(root, settings):
        print("tradeloop_cycle=LIVE_NOT_READY")
        return 2
    if mode in _MODE_DAGS and not _portfolio_state(root).positions:
        # Holdings-focused modes have nothing to review on an empty book; skip
        # before prepare/scan/LLM so it costs zero tokens. Premarket owns
        # new-entry discovery and is never gated on holdings.
        print("tradeloop_cycle=SKIP reason=no_holdings")
        return 0

    _pending_auto_route: Path | None = None  # set inside the lock if auto-routing
    with _global_lock(root) as acquired:
        if not acquired:
            print("tradeloop_cycle=LOCKED")
            return 0
        if run_dir is not None:  # resume in place: never re-prepare (and re-bill) a paid-for run
            run_dir = Path(run_dir)
        else:
            run_dir = _prepare(mode, request, root=root) if _prepare_takes_root() else _prepare(mode, request)
        gates = [
            _gate("holiday", "Market holiday", "passed", "NSE trading day"),
            _gate("kill_switch", "Kill switch", "passed", "kill switch is not active"),
            _gate(
                "live_promotion",
                "Live promotion",
                "passed" if live_active else "not_applicable",
                "live promotion gate cleared" if live_active else "paper route does not need live promotion",
            ),
        ]
        _write_gate_summary(
            run_dir,
            mode=mode,
            phase="reasoning",
            settings=settings,
            gates=gates,
            summary="Reasoning started after preflight gates passed.",
        )
        rc = _run_reasoning(run_dir, mode, backend, settings.cycle_timeout_seconds,
                            settings=settings, root=root)
        if rc == -1:
            _write_gate_summary(
                run_dir, mode=mode, phase="failed", settings=settings, gates=gates,
                summary="Reasoning timed out before an order decision was produced.")
            print("tradeloop_cycle=TIMEOUT")
            return 1
        if rc != 0:
            _write_gate_summary(
                run_dir, mode=mode, phase="failed", settings=settings, gates=gates,
                summary=f"Reasoning failed with rc={rc}.")
            print(f"tradeloop_cycle=REASONING_FAILED rc={rc}")
            return 1

        # Validate now so a bad orders.json fails loudly at propose time, not
        # at approval time.
        try:
            orders = load_orders(run_dir / "orders.json").orders
            n_orders = len(orders)
            gates.append(_gate("orders_schema", "Order schema", "passed",
                               f"orders.json validated with {n_orders} proposed order(s)"))
        except Exception:
            gates.append(_gate("orders_schema", "Order schema", "blocked",
                               "orders.json could not be validated"))
            _write_gate_summary(
                run_dir, mode=mode, phase="failed", settings=settings, gates=gates,
                summary="The run produced an invalid orders file.")
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
                gates.append(_gate("evidence", "Evidence citations", "blocked",
                                   f"missing {len(ev.missing)} cited evidence item(s)"))
                _write_gate_summary(
                    run_dir, mode=mode, phase="blocked", settings=settings, gates=gates,
                    summary="The evidence gate blocked the proposal.")
                print(f"tradeloop_cycle=EVIDENCE_INVALID missing={len(ev.missing)} run_dir={run_dir}")
                return 1
            gates.append(_gate("evidence", "Evidence citations", "passed",
                               "all referenced evidence exists"))
        else:
            gates.append(_gate("evidence", "Evidence citations", "skipped",
                               "no frozen snapshot was present", "warning"))

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
                gates.append(_gate("price_grounding", "Price grounding", "blocked",
                                   f"{len(gr.violations)} order level(s) did not match the frozen scan"))
                _write_gate_summary(
                    run_dir, mode=mode, phase="blocked", settings=settings, gates=gates,
                    summary="The price-grounding gate blocked the proposal.")
                print(f"tradeloop_cycle=PRICE_UNGROUNDED violations={len(gr.violations)} run_dir={run_dir}")
                return 1
            gates.append(_gate("price_grounding", "Price grounding", "passed",
                               "entry and stop levels match the frozen scan"))
        else:
            gates.append(_gate("price_grounding", "Price grounding", "skipped",
                               "no frozen scanner levels were present", "warning"))

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
                gates.append(_gate("analysis_quality", "Analysis quality", "blocked",
                                   "hard_block/new_buys quality line present"))
                _write_gate_summary(
                    run_dir, mode=mode, phase="blocked", settings=settings, gates=gates,
                    summary="The analysis-quality gate blocked new BUY orders.")
                print(f"tradeloop_cycle=QUALITY_BLOCKED run_dir={run_dir}")
                return 1
        gates.append(_gate("analysis_quality", "Analysis quality", "passed",
                           "no hard block on new BUY orders was present"))

        if settings.approval_mode != "auto":
            _write_gate_summary(
                run_dir, mode=mode, phase="awaiting_approval", settings=settings, gates=gates,
                summary="Proposal is waiting for human approval.")
            print(f"tradeloop_cycle=AWAITING_APPROVAL mode={mode} orders={n_orders} run_dir={run_dir}")
            return 0

        # Auto mode: check per-ticket conviction before releasing the lock.
        # Holdings-management modes (intraday/postclose) have no trade plan, so the
        # gate is a no-op for them. Only premarket/adhoc BUY entries are checked.
        block = _conviction_gate(run_dir, orders, settings.auto_route_min_conviction)
        if block:
            rescued, retry_block = _manager_backchannel_retry(
                run_dir,
                mode=mode,
                backend=backend,
                settings=settings,
            )
            if rescued:
                orders = load_orders(run_dir / "orders.json").orders
                n_orders = len(orders)
                print(f"tradeloop_cycle=MANAGER_REVISED_FOR_ROUTE run_dir={run_dir}")
            else:
                _write_fills_summary(
                    run_dir,
                    success=False,
                    n_orders=n_orders,
                    reason=retry_block or block,
                )
                _record_conviction_block_feedback(
                    root / "memory",
                    run_dir,
                    orders,
                    threshold=settings.auto_route_min_conviction,
                    reason=retry_block or block,
                    timestamp=_now_iso(),
                )
                gates.append(_gate("conviction", "Minimum conviction", "blocked",
                                   retry_block or block))
                _write_gate_summary(
                    run_dir, mode=mode, phase="blocked", settings=settings, gates=gates,
                    summary="The minimum-conviction gate blocked auto-routing.")
                print(
                    f"tradeloop_cycle=CONVICTION_BLOCKED reason={retry_block or block} "
                    f"run_dir={run_dir}")
                return 1
        gates.append(_gate("conviction", "Minimum conviction", "passed",
                           f"all BUY orders meet min={settings.auto_route_min_conviction}"))

        _write_gate_summary(
            run_dir, mode=mode, phase="auto_routing", settings=settings, gates=gates,
            summary="Auto-routing started after all propose gates passed.")
        print(f"tradeloop_cycle=AUTO_ROUTING mode={mode} orders={n_orders} run_dir={run_dir}")
        _pending_auto_route = run_dir

    # Global lock released above. route_cycle re-acquires it independently so
    # there is no self-deadlock; the ALREADY_ROUTED guard in route_cycle prevents
    # a double-fill if the process is somehow re-entered between the two calls.
    if _pending_auto_route is not None:
        rc = route_cycle(_pending_auto_route, root=root)
        _write_fills_summary(_pending_auto_route, success=(rc == 0), n_orders=n_orders)
        return rc
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
        current_orders = load_orders(orders_path)
        try:
            routed = route_orders_file(orders_path, fills_path, book, settings, root=root, ledger=led, mode=cycle_mode,
                                       live_route_authorized=live_enabled())
        except Exception as exc:  # malformed orders.json -> loud abort, no routing
            fills_path.write_text(json.dumps({"error": "ORDERS_INVALID", "detail": str(exc)}), encoding="utf-8")
            print("tradeloop_route=ORDERS_INVALID")
            return 1
        rejected_map = _fixable_route_rejections(routed)
        if rejected_map:
            rescued, retry_reason = _manager_route_rejection_retry(
                run_dir,
                mode=cycle_mode,
                generated_by=current_orders.generated_by or "",
                settings=settings,
                rejected=rejected_map,
            )
            if rescued:
                current_orders = load_orders(orders_path)
                try:
                    routed = route_orders_file(orders_path, fills_path, book, settings, root=root, ledger=led,
                                               mode=cycle_mode, live_route_authorized=live_enabled())
                except Exception as exc:
                    fills_path.write_text(json.dumps({"error": "ORDERS_INVALID", "detail": str(exc)}), encoding="utf-8")
                    print("tradeloop_route=ORDERS_INVALID")
                    return 1
                second_rejected = _route_reject_reason_map(routed)
                if second_rejected and not any(str(getattr(item, "status", "")).upper() == "FILLED"
                                               for item in routed):
                    backend = _backend_for_generated_by(current_orders.generated_by)
                    _write_manager_backchannel(run_dir, {
                        "event": "route_risk_rejected",
                        "status": "still_rejected_after_retry",
                        "backend": backend,
                        "model": _strongest_manager_model(backend),
                        "initial_block_reason": json.dumps(rejected_map, sort_keys=True),
                        "retry_block_reason": json.dumps(second_rejected, sort_keys=True),
                        "manager_response": {"orders": [o.model_dump() for o in current_orders.orders]},
                    })
                    print(f"tradeloop_route=MANAGER_REPAIR_BLOCKED reason={json.dumps(second_rejected, sort_keys=True)}")
            elif retry_reason:
                print(f"tradeloop_route=MANAGER_REPAIR_BLOCKED reason={retry_reason}")
        # Persist this cycle's FILLED fills — the whole point of the book.
        # Without this append, positions would not survive to the next cycle.
        new_fills = [f for f in book.fills[pre_fills:] if f.status == "FILLED"]
        if new_fills:
            approved = current_orders.orders
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
        summary_data = _load_json_file(run_dir / "gate_summary.json")
        gates = list(summary_data.get("gates", [])) if isinstance(summary_data, dict) else []
        route_status = "passed" if rejected == 0 and mode_blocked == 0 else "blocked"
        gates.append(_gate(
            "route_risk",
            "Route risk engine",
            route_status,
            f"{filled} filled, {rejected} risk-rejected, {mode_blocked} mode-blocked",
        ))
        _write_gate_summary(
            run_dir,
            mode=cycle_mode,
            phase="routed" if route_status == "passed" else "blocked",
            settings=settings,
            gates=gates,
            summary=(
                "Paper/live route completed after deterministic gates passed."
                if route_status == "passed" else
                "Route completed with deterministic blocks."
            ),
        )
        _record_route_feedback(root / "memory", run_dir, current_orders, routed,
                               timestamp=_now_iso())
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
