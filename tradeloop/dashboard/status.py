from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tradeloop.lib.approval import validate_approval
from tradeloop.lib.broker.live_state import load_reconciliation
from tradeloop.lib.broker.router import live_enabled
from tradeloop.lib.config import load_settings
from tradeloop.lib.live.promotion import evaluate_live_promotion
from tradeloop.lib.risk.circuit_breaker import kill_switch_active
from tradeloop.scripts.verify_setup import source_health


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _proposed_order_count(run_dir: Path) -> int:
    orders = _load_json(run_dir / "orders.json")
    if not isinstance(orders, dict):
        return 0
    return len(orders.get("orders") or [])


def _latest_run(runs_dir: Path) -> dict | None:
    if not runs_dir.is_dir():
        return None
    runs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    if not runs:
        return None
    run_dir = runs[0]
    proposed_orders = _proposed_order_count(run_dir)
    fills = _load_json(run_dir / "fills.json")
    controls = _load_json(run_dir / "controls.json")
    reconcile = load_reconciliation(run_dir)

    approval = "not_required"
    if proposed_orders:
        # Auto-routed runs never write approval.json - check fills first.
        # An empty [] fills.json is the prepare-cycle placeholder (not a real route);
        # only a non-empty list means route_cycle actually ran.
        fills = _load_json(run_dir / "fills.json")
        if isinstance(fills, list) and fills:
            # route_cycle ran (auto mode); any non-empty fills = auto_routed
            approval = "auto_routed"
        else:
            # No real fills yet - check if conviction gate blocked it
            summary_path = run_dir / "fills_summary.md"
            if summary_path.exists():
                try:
                    if "result: BLOCKED" in summary_path.read_text(encoding="utf-8"):
                        approval = "conviction_blocked"
                except OSError:
                    pass
            if approval == "not_required":
                # Human-in-loop path: look for a human approval artifact
                try:
                    approval_status = validate_approval(run_dir, run_dir / "orders.json")
                    approval = "approved" if approval_status.ok else "missing_or_invalid"
                except (OSError, ValueError):
                    approval = "missing_or_invalid"

    controls_status = "missing"
    if isinstance(controls, dict):
        severities = {str(d.get("severity", "")) for d in controls.get("deficiencies", [])}
        if severities & {"material_weakness", "significant_deficiency"}:
            controls_status = "critical_deficiency"
        elif controls.get("deficiencies"):
            controls_status = "deficiencies"
        else:
            controls_status = "clean"

    return {
        "dir": run_dir.name,
        "proposed_orders": proposed_orders,
        "approval": approval,
        "routed": bool(fills),
        "controls": controls_status,
        "live_snapshot_present": (run_dir / "live_broker_snapshot.json").exists(),
        "live_reconciliation": "missing" if reconcile is None else "clean" if reconcile.ok else "blocked",
    }


def _promotion(root: Path) -> dict:
    try:
        return asdict(evaluate_live_promotion(root, load_settings(root / "config" / "settings.yaml")))
    except Exception:
        return {
            "ready": False,
            "reasons": ["promotion status unavailable"],
            "closed_paper_trades": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "max_drawdown_r": 0.0,
            "clean_audits": False,
        }


def _autonomy(settings, live_env_enabled: bool, kill_active: bool) -> dict:
    if kill_active:
        effective = "halted"
    elif live_env_enabled and settings.approval_mode == "auto" and settings.allow_auto_live:
        effective = "live_auto_enabled"
    elif live_env_enabled:
        effective = "live_locked"
    elif settings.approval_mode == "auto":
        effective = "paper_autonomous"
    else:
        effective = "paper_human_loop"
    return {
        "approval_mode": settings.approval_mode,
        "paper_auto_route": settings.approval_mode == "auto" and not live_env_enabled,
        "allow_auto_live": settings.allow_auto_live,
        "live_trading_env_enabled": live_env_enabled,
        "effective_mode": effective,
    }


def _operator_attention(*, kill_active: bool, live_env_enabled: bool,
                        promo: dict, sources: dict, latest: dict | None) -> list[dict]:
    items: list[dict] = []
    if kill_active:
        items.append({"severity": "critical", "title": "Kill switch active",
                      "detail": "No routes will execute until the kill switch is cleared."})
    if live_env_enabled:
        items.append({"severity": "warning", "title": "Live trading env is enabled",
                      "detail": "Paper-first mode should normally keep ZERODHA_ENABLE_TRADING=false."})
    if not promo.get("ready"):
        reasons = "; ".join(str(r) for r in promo.get("reasons", [])[:3]) or "promotion gates not clear"
        items.append({"severity": "info", "title": "Live promotion blocked", "detail": reasons})
    if not sources.get("ok"):
        stale = ", ".join(str(s) for s in sources.get("stale_sources", []))
        items.append({"severity": "warning", "title": "Market sources stale", "detail": stale})
    if latest and latest.get("approval") in {"missing_or_invalid", "conviction_blocked"}:
        items.append({"severity": "warning", "title": "Latest run needs review",
                      "detail": f"Approval state: {latest.get('approval')}"})
    return items


def dashboard_status(root: Path) -> dict:
    root = Path(root)
    settings = load_settings(root / "config" / "settings.yaml")
    stale_sources = source_health(root)
    sources = {
        "ok": not stale_sources,
        "stale_sources": stale_sources,
    }
    kill_active = kill_switch_active(root)
    live_env = live_enabled()
    promo = _promotion(root)
    latest = _latest_run(root / "runs")
    return {
        "kill_switch_active": kill_active,
        "live_trading_env_enabled": live_env,
        "autonomy": _autonomy(settings, live_env, kill_active),
        "live_promotion": promo,
        "source_health": sources,
        "latest_run": latest,
        "operator_attention": _operator_attention(
            kill_active=kill_active,
            live_env_enabled=live_env,
            promo=promo,
            sources=sources,
            latest=latest,
        ),
    }
