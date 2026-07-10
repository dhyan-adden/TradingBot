import os
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from tradeloop.lib.audit.ledger import Ledger, RISK_VERDICT
from tradeloop.lib.broker.orders_schema import load_orders, to_ticket
from tradeloop.lib.broker.paper_broker import Fill, OrderTicket, PaperBroker
from tradeloop.lib.broker.zerodha_mcp import to_zerodha_payload
from tradeloop.lib.config import Settings
from tradeloop.lib.config import risk_caps as risk_caps_from
from tradeloop.lib.data.ticker_master import load_ticker_master
from tradeloop.lib.risk.checks import RiskDecision, RiskState, evaluate
from tradeloop.lib.risk.circuit_breaker import kill_switch_active


# Cycle-mode trading policy (00_master_orchestrator.md lines 45-47): premarket/adhoc
# may open new longs; intraday manages existing longs only (exits, no new entries);
# postclose never trades. Enforced deterministically at the route gate below so the
# contract holds regardless of which backend or human authored orders.json - the LLM
# proposing an out-of-mode order can no longer route it.
_MODE_ALLOWED_SIDES: Dict[str, set] = {
    "premarket": {"BUY", "SELL"},
    "adhoc": {"BUY", "SELL"},
    "intraday": {"SELL"},
    "postclose": set(),
}


def _sides_for_mode(mode: str) -> set:
    # Unknown mode -> permissive (premarket semantics), preserving the pre-gate
    # behaviour for direct callers/tests that pass no mode.
    return _MODE_ALLOWED_SIDES.get(str(mode).strip().lower(), {"BUY", "SELL"})


@dataclass(frozen=True)
class RoutedOrder:
    mode: str
    status: str
    payload: Dict[str, object]


def live_enabled() -> bool:
    return os.getenv("ZERODHA_ENABLE_TRADING", "false").strip().lower() == "true"


def route_order(
    ticket: OrderTicket,
    paper_broker: PaperBroker,
    confirm_live: bool = False,
    root: Path = Path("tradeloop"),
) -> RoutedOrder:
    if kill_switch_active(root):
        return RoutedOrder("blocked", "KILL_SWITCH_ACTIVE", {"symbol": ticket.symbol, "side": ticket.side})
    if not live_enabled():
        fill: Fill = paper_broker.place_order(ticket)
        return RoutedOrder("paper", fill.status, fill.__dict__)
    if not live_promotion_ready(root):
        return RoutedOrder("blocked", "LIVE_PROMOTION_GATE_NOT_CLEARED", {"symbol": ticket.symbol, "side": ticket.side})
    payload = to_zerodha_payload(ticket, confirm=confirm_live)
    return RoutedOrder("live_mcp_required", "READY_FOR_CODEX_TOOL_CALL", payload)


def live_promotion_ready(root: Path = Path("tradeloop"), settings: "Settings | None" = None) -> bool:
    performance = root / "memory" / "strategy_performance.md"
    if not performance.exists():
        return False
    text = performance.read_text(encoding="utf-8").lower()
    if "live_ready: true" in text:
        return True
    gates = settings.promotion_gates if settings else {}
    min_trades = float(gates.get("min_paper_trades", 40))
    min_win = float(gates.get("min_win_rate", 0.45))
    min_exp = float(gates.get("min_expectancy_r", 0.3))
    max_dd = float(gates.get("max_drawdown_pct", 8))
    paper_trades = _metric(text, "paper_trades")
    win_rate = _metric(text, "win_rate")
    expectancy = _metric(text, "expectancy_r")
    drawdown = _metric(text, "max_drawdown_pct")
    return paper_trades >= min_trades and win_rate >= min_win and expectancy >= min_exp and drawdown <= max_dd


def _metric(text: str, key: str) -> float:
    match = re.search(rf"{re.escape(key)}\s*:\s*([-+]?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else 0.0


def _equity(book: PaperBroker) -> float:
    deployed = sum(qty * book.avg_prices.get(sym, 0.0) for sym, qty in book.positions.items())
    return book.cash_inr + deployed


def _risk_state(book: PaperBroker, sectors: Dict[str, str]) -> RiskState:
    return RiskState(
        cash_inr=book.cash_inr,
        positions=dict(book.positions),
        avg_prices=dict(book.avg_prices),
        sectors=dict(sectors),  # full ticker-master map: an incoming NEW symbol's sector must be known to the sector cap, not just symbols already held
        open_risk_inr=0.0,   # best-effort in P0; full from persisted stops + marks in P3
        daily_pnl_inr=0.0,   # realized-only; unrealized deferred to P3 marks
    )


def append_decision(path: Path, order, verdict, routed: RoutedOrder) -> None:
    record = {
        "ticker": order.ticker,
        "side": order.side,
        "quantity": order.quantity,
        "price": order.price,
        "approved": verdict.approved,
        "reasons": verdict.reasons,
        "routed_status": routed.status,
        "routed_mode": routed.mode,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def _scan_symbols(run_dir: Path) -> set:
    """Tickers actually scanned this cycle (<run>/full_scan.jsonl) - the eligible
    route universe when universe.source=full_nse. Absent/unreadable -> empty set,
    so routing falls back to the config base + current holdings."""
    try:
        lines = (run_dir / "full_scan.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    out = set()
    for line in lines:
        try:
            ticker = json.loads(line).get("ticker")
        except ValueError:
            continue
        if ticker:
            out.add(str(ticker).strip().upper())
    return out


def route_orders_file(
    orders_path: Path,
    fills_path: Path,
    book: PaperBroker,
    settings: Settings,
    root: Path = Path("tradeloop"),
    ledger: "Ledger | None" = None,
    mode: str = "premarket",
) -> list[RoutedOrder]:
    of = load_orders(orders_path)  # typed; raises on malformed -> cycle aborts loudly
    records = load_ticker_master(root / "config" / "universe.yaml")
    # ponytail: sectors only cover the config base; full_scan.jsonl carries no
    # sector, so the sector cap binds only where a sector is known. Add sector to
    # the scan record to extend it to full-NSE names.
    sectors = {r.symbol.upper(): r.sector for r in records}
    # Eligible route universe = names actually scanned this cycle (trust the run's
    # scan under source=full_nse) + the config base + current holdings, so a held
    # name is always exitable even if today's scan drops it.
    symbols = sorted(_scan_symbols(orders_path.parent)
                     | {r.symbol.upper() for r in records}
                     | {s.upper() for s in book.positions})
    caps = risk_caps_from(settings, symbols, _equity(book))  # capital base fixed at start-of-batch equity
    allowed_sides = _sides_for_mode(mode)
    decisions_path = orders_path.parent / "decisions.jsonl"
    routed: list[RoutedOrder] = []
    for order in of.orders:  # held[] intentionally skipped in Phase 0
        # Rebuild the risk state from the LIVE book each order, so a fill earlier
        # in this batch counts toward the cumulative caps (deployment, position
        # count, sector) when the next order is gated. Built once, a second order
        # would be judged against stale pre-batch state and could breach them.
        state = _risk_state(book, sectors)
        ticket = to_ticket(order)
        if ticket.side.strip().upper() not in allowed_sides:
            # Out-of-mode order (e.g. a BUY in intraday/postclose): block before the
            # risk gate so a wrong-cycle new entry can never fill. Recorded like any
            # other rejection for the audit trail.
            verdict = RiskDecision(approved=False,
                                   reasons=[f"mode_{mode}_disallows_{order.side}"])
            outcome = RoutedOrder("blocked", "MODE_DISALLOWED",
                                  {"symbol": ticket.symbol, "side": ticket.side, "mode": mode})
        else:
            verdict = evaluate(ticket, state, caps)  # the mandatory gate
            if not verdict.approved:
                outcome = RoutedOrder("blocked", "RISK_REJECTED",
                                      {"symbol": ticket.symbol, "reasons": verdict.reasons})
            else:
                outcome = route_order(ticket, book, root=root)
        routed.append(outcome)
        append_decision(decisions_path, order, verdict, outcome)
        if ledger is not None:
            ledger.append({
                "type": RISK_VERDICT,
                "symbol": ticket.symbol.strip().upper(),
                "side": ticket.side,
                "quantity": ticket.quantity,
                "price": ticket.price,
                "approved": verdict.approved,
                "reasons": verdict.reasons,
            })
    fills_path.write_text(json.dumps([r.__dict__ for r in routed], indent=2, default=str), encoding="utf-8")
    return routed
