#!/usr/bin/env python
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradeloop.lib.audit.ledger import ORDER_FILLED, STOP_UPDATED, Ledger
from tradeloop.lib.broker.paper_book import hydrate
from tradeloop.lib.data.ingest import run as ingest_run
from tradeloop.lib.data.kite import KiteClient
from tradeloop.lib.data.snapshot import render_news_raw, render_setups
from tradeloop.lib.portfolio.state import PortfolioState, empty_state_from_settings, render_context
from tradeloop.lib.util.ist_clock import IST


ROOT = Path(__file__).resolve().parents[1]


def _portfolio_state(base: Path) -> PortfolioState:
    """Real book state for 00_context so cycles see and manage open positions
    (an empty context made agents reason over a flat book while holding fills).
    Falls back to the empty state when no ledger exists (fresh deploys, tests)."""
    settings_path = base / "config" / "settings.yaml"
    ledger_path = base / "state" / "ledger.db"
    empty = empty_state_from_settings(settings_path)
    if not ledger_path.exists():
        return empty
    book = hydrate(ledger_path, empty.cash_inr)
    stops = {}
    for event in Ledger(ledger_path).replay([ORDER_FILLED, STOP_UPDATED]):
        if float(event.get("hard_stop", 0.0)) > 0:
            stops[event["symbol"]] = float(event["hard_stop"])
    stops = {s: v for s, v in stops.items() if book.positions.get(s, 0) > 0}
    equity = book.cash_inr + sum(
        q * book.avg_prices.get(s, 0.0) for s, q in book.positions.items())
    return PortfolioState(cash_inr=book.cash_inr, positions=dict(book.positions),
                          avg_prices=dict(book.avg_prices), hard_stops=stops,
                          equity_inr=equity)


def prepare(mode: str, request: str = "", root: Path | None = None, kite_client=None) -> Path:
    base = root or ROOT
    now = datetime.now(IST)
    run_dir = base / "runs" / f"{now:%Y-%m-%d_%H%M}_{mode}"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = _portfolio_state(base)
    macro_path = base / "memory" / "macro_view.md"
    macro = macro_path.read_text(encoding="utf-8") if macro_path.exists() else ""
    carry_forward_path = base / "memory" / "carry_forward_context.md"
    carry_forward = carry_forward_path.read_text(encoding="utf-8") if carry_forward_path.exists() else ""
    context = render_context(state, mode, macro)
    if carry_forward.strip():
        context = "\n".join([context.rstrip(), "", "## Carry Forward Context", "", carry_forward.strip(), ""])
    (run_dir / "00_context.md").write_text(context, encoding="utf-8")
    if mode == "adhoc":
        request_text = request.strip()
        if not request_text:
            raise ValueError("adhoc mode requires --request text")
        (run_dir / "user_request.md").write_text(f"# User Request\n\n{request_text}\n", encoding="utf-8")

    # Real research ingest behind the renderers: fetch news + Kite setups,
    # tag, freeze the hashed snapshot, render 01_news_raw / 02_setups_raw.
    # base-relative config so --root / isolated deployments read the right universe.
    # Live Kite scan is opt-in via ZERODHA_ENABLE_DATA=true (read-only market data;
    # kept independent of ZERODHA_ENABLE_TRADING so paper cycles still scan real
    # setups). A stale/absent token degrades to an empty scan, not a crash, because
    # scan_universe tolerates per-symbol data errors. Tests inject kite_client directly.
    if kite_client is None and os.getenv("ZERODHA_ENABLE_DATA", "false").strip().lower() == "true":
        kite_client = KiteClient()
    # Non-order modes review the book, not the market: scan only held symbols
    # (an empty book scans nothing) and snapshot their live LTPs for the
    # deterministic stop-breach check and the holdings reviewer.
    holdings_scoped = mode in ("intraday", "postclose")
    held = sorted(state.positions) if holdings_scoped else []
    scope = {"symbols": held} if holdings_scoped else {}
    try:
        ingest_run(now, run_dir=run_dir, config_dir=base / "config", kite_client=kite_client,
                   source_health_root=base, **scope)
    except Exception as exc:  # degrade-not-abort: never leave a silent blank
        (run_dir / "01_news_raw.md").write_text(
            render_news_raw([], [], news_available=False), encoding="utf-8")
        (run_dir / "02_setups_raw.md").write_text(render_setups([]), encoding="utf-8")
        (run_dir / "ingest_error.txt").write_text(f"ingest failed: {exc}\n", encoding="utf-8")
    if holdings_scoped and kite_client is not None and held:
        try:
            ltps = kite_client.ltp(held)
            if ltps:
                (run_dir / "holdings_ltp.json").write_text(
                    json.dumps(ltps, indent=2), encoding="utf-8")
        except Exception as exc:  # stale token etc.: review still runs, breach check skips
            (run_dir / "ltp_error.txt").write_text(f"ltp fetch failed: {exc}\n", encoding="utf-8")
    artifact_names = [
        "10_news.md",
        "11_sentiment.md",
        "12_fundamentals.md",
        "13_technical.md",
        "14_shortlist.md",
        "20_bull.md",
        "21_bear.md",
        "22_debate.md",
        "30_trade_plan.md",
        "40_risk_report.md",
        "41_pm_decision.md",
        "50_post_trade.md",
    ]
    if mode == "adhoc":
        artifact_names.insert(0, "05_adhoc_intake.md")
    for name in artifact_names:
        path = run_dir / name
        if not path.exists():
            path.write_text(f"# {name.removesuffix('.md').replace('_', ' ').title()}\n\nPending.\n", encoding="utf-8")
    for name in ["orders.json", "fills.json"]:
        path = run_dir / name
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="premarket", choices=["premarket", "intraday", "postclose", "adhoc"])
    parser.add_argument("--request", default="")
    args = parser.parse_args()
    run_dir = prepare(args.mode, args.request)
    print(f"tradeloop_run_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
