"""Phase 9: live route requires Zerodha account state to match TradeLoop state.

The gate reads a persisted reconciliation result (`live_reconcile.json`) that a
broker fetch step writes before routing. Without a fresh, passing result the
live route is blocked - it must never rely on paper ledger state alone.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from tradeloop.lib.broker.live_book import load_live_expected_book

SNAPSHOT_FILE = "live_broker_snapshot.json"
RECONCILE_FILE = "live_reconcile.json"
MAX_AGE_SECONDS = 120


@dataclass(frozen=True)
class LiveBrokerSnapshot:
    # No secrets: only positions, open orders, and available cash.
    checked_at: str
    auth_ok: bool
    holdings: Dict[str, int]
    open_orders: List[dict]
    available_cash_inr: float


@dataclass(frozen=True)
class LiveReconciliationStatus:
    ok: bool
    reasons: List[str]
    symbols_checked: List[str]
    open_order_conflicts: List[str]
    checked_at: str


def _age_seconds(checked_at: str, now: datetime | None = None) -> float:
    try:
        ct = datetime.fromisoformat(checked_at)
    except ValueError:
        return float("inf")
    if ct.tzinfo is None:
        ct = ct.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - ct).total_seconds()


def compute_reconciliation(
    snapshot: LiveBrokerSnapshot,
    orders: list,
    expected_book: Dict[str, int],
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> LiveReconciliationStatus:
    reasons: List[str] = []
    conflicts: List[str] = []
    symbols = sorted(set(expected_book) | {
        str(getattr(o, "symbol", getattr(o, "ticker", ""))).strip().upper() for o in orders})

    if not snapshot.auth_ok:
        reasons.append("broker auth failure")
    if _age_seconds(snapshot.checked_at) > max_age_seconds:
        reasons.append("broker snapshot stale")

    if snapshot.auth_ok:
        for sym, qty in expected_book.items():
            sym = sym.strip().upper()
            held = snapshot.holdings.get(sym, 0)
            if held != qty:
                reasons.append(f"holdings mismatch {sym}: broker={held} tradeloop={qty}")
        for o in orders:
            sym = str(getattr(o, "symbol", getattr(o, "ticker", ""))).strip().upper()
            side = str(getattr(o, "side", "")).strip().upper()
            qty = int(getattr(o, "quantity", 0))
            if side == "SELL":
                broker_held = snapshot.holdings.get(sym, 0)
                live_book = expected_book.get(sym, 0)
                if qty > broker_held:
                    reasons.append(
                        f"SELL {sym} qty {qty} exceeds broker-held {broker_held}")
                if qty > live_book:
                    reasons.append(
                        f"SELL {sym} qty {qty} exceeds live-book {live_book} "
                        "(only broker-confirmed live positions are sellable)")
        buy_notional = sum(
            int(getattr(o, "quantity", 0)) * float(getattr(o, "price", 0) or 0)
            for o in orders if str(getattr(o, "side", "")).strip().upper() == "BUY")
        if buy_notional > snapshot.available_cash_inr:
            reasons.append(
                f"proposed BUY notional {buy_notional} exceeds available cash "
                f"{snapshot.available_cash_inr}")
    for o in orders:
        sym = str(getattr(o, "symbol", getattr(o, "ticker", ""))).strip().upper()
        side = str(getattr(o, "side", "")).strip().upper()
        for oo in snapshot.open_orders:
            if (str(oo.get("symbol", "")).strip().upper() == sym
                    and str(oo.get("side", "")).strip().upper() == side):
                conflicts.append(f"{sym}/{side}")
    if conflicts:
        reasons.append(f"duplicate open order(s): {', '.join(conflicts)}")

    return LiveReconciliationStatus(
        ok=not reasons, reasons=reasons, symbols_checked=symbols,
        open_order_conflicts=conflicts, checked_at=snapshot.checked_at)


def persist_snapshot(run_dir: Path, snapshot: LiveBrokerSnapshot) -> None:
    (Path(run_dir) / SNAPSHOT_FILE).write_text(
        json.dumps(asdict(snapshot), indent=2), encoding="utf-8")


def persist_reconciliation(run_dir: Path, status: LiveReconciliationStatus) -> None:
    (Path(run_dir) / RECONCILE_FILE).write_text(
        json.dumps(asdict(status), indent=2), encoding="utf-8")


def load_reconciliation(run_dir: Path) -> LiveReconciliationStatus | None:
    path = Path(run_dir) / RECONCILE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return LiveReconciliationStatus(
        ok=bool(data.get("ok")),
        reasons=list(data.get("reasons", [])),
        symbols_checked=list(data.get("symbols_checked", [])),
        open_order_conflicts=list(data.get("open_order_conflicts", [])),
        checked_at=str(data.get("checked_at", "")),
    )


def live_reconcile_allows_route(run_dir: Path, max_age_seconds: int = MAX_AGE_SECONDS) -> bool:
    status = load_reconciliation(run_dir)
    if status is None or not status.ok:
        return False
    return _age_seconds(status.checked_at) <= max_age_seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_snapshot(run_dir: Path) -> LiveBrokerSnapshot | None:
    """Load the sanitized broker snapshot written by the TS producer. Malformed
    or missing file -> None (fail closed)."""
    path = Path(run_dir) / SNAPSHOT_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        holdings: Dict[str, int] = {}
        for sym, qty in (data.get("holdings") or {}).items():
            key = str(sym).strip().upper()
            if key and int(qty) > 0:
                holdings[key] = int(qty)
        return LiveBrokerSnapshot(
            checked_at=str(data.get("checked_at", "")),
            auth_ok=bool(data.get("auth_ok")),
            holdings=holdings,
            open_orders=list(data.get("open_orders") or []),
            available_cash_inr=float(data.get("available_cash_inr", 0.0)),
        )
    except (ValueError, OSError, TypeError):
        return None


def refresh_live_reconciliation(
    run_dir: Path,
    root: Path,
    orders_path: Path,
    timeout_seconds: int = 30,
) -> LiveReconciliationStatus:
    """Run the read-only TS snapshot producer, then recompute and persist a
    fresh reconciliation. Any fetch failure fails closed and persists a not-ok
    status so the route gate blocks. Paper routes never call this."""
    run_dir = Path(run_dir)
    root = Path(root)
    orders_path = Path(orders_path)
    failed = LiveReconciliationStatus(
        ok=False, reasons=["broker snapshot fetch failed"],
        symbols_checked=[], open_order_conflicts=[], checked_at=_now_iso())

    npm_root = root
    if not (npm_root / "package.json").is_file() and (root.parent / "package.json").is_file():
        npm_root = root.parent

    try:
        proc = subprocess.run(
            ["npm", "run", "--silent", "live:snapshot", "--", "--run-dir", str(run_dir)],
            cwd=npm_root, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired):
        persist_reconciliation(run_dir, failed)
        return failed
    if proc.returncode != 0:
        persist_reconciliation(run_dir, failed)
        return failed

    snapshot = load_snapshot(run_dir)
    if snapshot is None:
        missing = LiveReconciliationStatus(
            ok=False, reasons=["broker snapshot missing or malformed after fetch"],
            symbols_checked=[], open_order_conflicts=[], checked_at=_now_iso())
        persist_reconciliation(run_dir, missing)
        return missing

    try:
        expected_book = load_live_expected_book(root)
    except ValueError as exc:
        bad_book = LiveReconciliationStatus(
            ok=False, reasons=[str(exc)],
            symbols_checked=[], open_order_conflicts=[], checked_at=_now_iso())
        persist_reconciliation(run_dir, bad_book)
        return bad_book

    from tradeloop.lib.broker.orders_schema import load_orders
    try:
        orders = load_orders(orders_path).orders
    except Exception as exc:  # malformed orders.json -> block, never route
        bad_orders = LiveReconciliationStatus(
            ok=False, reasons=[f"orders.json unreadable: {exc}"],
            symbols_checked=[], open_order_conflicts=[], checked_at=_now_iso())
        persist_reconciliation(run_dir, bad_orders)
        return bad_orders

    status = compute_reconciliation(snapshot, orders, expected_book)
    persist_reconciliation(run_dir, status)
    return status
