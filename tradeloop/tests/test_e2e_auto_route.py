"""E2E auto-route test using real Friday 2026-08-21 scan data.

The scan artifacts (02_setups_raw.md, 03_market_regime.json) are copied from the
last live trading session so the test exercises real close-price scanner output.
LLM reasoning is stubbed with a realistic RELIANCE 20d-breakout trade at conviction
8.5 (above the 7.0 threshold) to keep the test deterministic and fast.

Asserts end-to-end that after the change:
  1. AUTO_ROUTING fires - not AWAITING_APPROVAL
  2. fills.json is present immediately after run_cycle()
  3. fills_summary.md (notification artifact) is written and says ROUTED
  4. RELIANCE is FILLED in the ledger
  5. A second route_cycle() call is blocked (ALREADY_ROUTED)
"""
import json
import shutil
from datetime import date
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.llm import schemas

# Real scanner output from the last trading session (Friday 2026-08-21).
# 295 setups, pullback_in_uptrend regime - genuine close-price data.
_FRIDAY_RUN = (
    Path(__file__).resolve().parents[1] / "runs" / "2026-08-21_1405_premarket"
)
_LAST_TRADING_DAY = date(2026, 8, 21)


class _FridayReasoningClient:
    """Stub LLM client that produces one realistic BUY for RELIANCE.

    The entry (2950) and stop (2850) are plausible Nifty-50 levels for a 20d
    breakout. Conviction 8.5 is above the 7.0 auto_route_min_conviction gate.
    All other stages return minimal-valid empty outputs.
    Accepts **kwargs so stage budget calls (max_tokens=...) pass through cleanly.
    """

    _DEFAULTS = {
        schemas.NewsAnalysis:      {"names_in_play": [], "evidence": []},
        schemas.SentimentReport:   {"scores": [], "evidence": []},
        schemas.FundamentalsReport:{"tags": [], "evidence": []},
        schemas.TechnicalReport:   {"setups": [], "evidence": []},
        schemas.Shortlist:         {"candidates": [], "evidence": []},
        schemas.HoldingsReview:    {"reviews": [], "carry_forward": "", "evidence": []},
        schemas.BullCase:          {"arguments": [], "evidence": []},
        schemas.BearCase:          {"arguments": [], "tier_c_only": [], "pump_risk": [], "evidence": []},
        schemas.Debate:            {"names": [], "evidence": []},
        schemas.RiskReport:        {"decisions": [], "evidence": []},
    }

    def call_json(self, role, system, user, schema, model=None, **kwargs):
        if schema is schemas.TradePlan:
            return schema.model_validate({
                "evidence": [],
                "tickets": [{
                    "ticker": "RELIANCE",
                    "side": "BUY",
                    "product": "CNC",
                    "strategy_family": "20d_breakout",
                    "entry": 1300.0,
                    "hard_stop": 1200.0,
                    "target_1": 1450.0,
                    "target_2": 1550.0,
                    "quantity": 15,         # deterministic sizer will overwrite
                    "time_horizon": "5-20 days",
                    "thesis": "RELIANCE 20d breakout - vol confirmation, regime pullback_in_uptrend",
                    "conviction": 8.5,      # above auto_route_min_conviction=7.0
                }],
            })
        if schema is schemas.PMDecision:
            return schema.model_validate({
                "evidence": [],
                "orders": [{
                    "ticker": "RELIANCE",
                    "side": "BUY",
                    "product": "CNC",
                    "quantity": 15,         # 15 × 1300 = 19,500 INR > 15,000 floor
                    "price": 1300.0,
                    "hard_stop": 1200.0,
                    "target_1": 1450.0,
                    "strategy_family": "20d_breakout",
                    "reason": "conviction 8.5 - 20d breakout thesis intact",
                }],
                "held": [],
            })
        return schema.model_validate(self._DEFAULTS[schema])


def test_e2e_premarket_auto_routes_on_last_trading_day(
    monkeypatch, tmp_path, capsys
):
    """Full premarket cycle with real Friday scan data - verifies AUTO_ROUTING."""
    # -- isolated root with real config -----------------------------------
    root = tmp_path / "tradeloop"
    src = Path(__file__).resolve().parents[1]
    for d in ("config", "state", "memory", "runs"):
        (root / d).mkdir(parents=True)
    shutil.copy(src / "config" / "settings.yaml", root / "config" / "settings.yaml")
    shutil.copy(src / "config" / "universe.yaml",  root / "config" / "universe.yaml")

    # -- run directory: real Friday inputs, no reasoning outputs ----------
    # The scan and regime artifacts are genuine: they were computed from live
    # Kite OHLCV data for 295 NSE symbols on 2026-08-21 (last trading session).
    run_dir = root / "runs" / "2026-08-21_0900_premarket"
    run_dir.mkdir()

    # Fresh empty-portfolio context so the 4-position cap does not block new entries
    (run_dir / "00_context.md").write_text(
        "# Context\nMode: premarket\nCash INR: 100000.0\nEquity INR: 100000.0\n"
        "Daily P&L INR: 0.0\n\n## Positions\n(none)\n",
        encoding="utf-8",
    )

    # Real Friday news digest - use live artifact if available, else stub
    news_src = _FRIDAY_RUN / "01_news_raw.md"
    if news_src.exists():
        shutil.copy(news_src, run_dir / "01_news_raw.md")
    else:
        (run_dir / "01_news_raw.md").write_text("# News\n(none)\n")

    # Real Friday scanner output: 295 setups from live Kite OHLCV data
    for artifact in ("02_setups_raw.md", "03_market_regime.json", "03_market_regime.md"):
        src_f = _FRIDAY_RUN / artifact
        if src_f.exists():
            shutil.copy(src_f, run_dir / artifact)
        else:
            (run_dir / artifact).write_text(f"# {artifact}\n")

    # -- patches ----------------------------------------------------------
    monkeypatch.setattr(orchestrator, "_today", lambda: _LAST_TRADING_DAY)

    client = _FridayReasoningClient()
    monkeypatch.setattr(
        orchestrator, "_run_reasoning",
        lambda run_dir, mode, backend, timeout, **kw: orchestrator._run_reasoning_dag(
            run_dir, mode, timeout, client,
            settings=kw.get("settings"), root=kw.get("root"),
        ),
    )

    # -- run --------------------------------------------------------------
    rc = orchestrator.run_cycle(
        "premarket", root=root, run_dir=run_dir, backend="openrouter"
    )
    out = capsys.readouterr().out

    # -- assertions -------------------------------------------------------
    assert rc == 0, f"expected rc=0, got {rc}\noutput:\n{out}"

    # Auto-routing fired - no human review step
    assert "tradeloop_cycle=AUTO_ROUTING" in out, (
        f"expected AUTO_ROUTING in output, got:\n{out}"
    )
    assert "tradeloop_route=OK" in out, f"route did not complete OK:\n{out}"
    assert "AWAITING_APPROVAL" not in out, "human review gate must not fire in auto mode"

    # Notification artifact exists and says ROUTED
    summary_path = run_dir / "fills_summary.md"
    assert summary_path.exists(), "fills_summary.md not written"
    summary = summary_path.read_text()
    assert "ROUTED" in summary, f"fills_summary.md should say ROUTED:\n{summary}"
    assert "fills_filled:" in summary, "fills count missing from summary"

    # fills.json written immediately - no second route_cycle needed
    fills = json.loads((run_dir / "fills.json").read_text())
    statuses = {f.get("status") for f in fills}
    assert "FILLED" in statuses, f"expected FILLED fill, got statuses={statuses}"
    assert "RISK_REJECTED" not in statuses, (
        "RELIANCE is in universe and within caps; should not be rejected"
    )

    # Position persisted to the ledger
    book = orchestrator.hydrate(root / "state" / "ledger.db", 100_000)
    assert book.positions.get("RELIANCE", 0) > 0, (
        "RELIANCE should appear as an open position in the book"
    )

    # Double-routing is blocked
    rc2 = orchestrator.route_cycle(run_dir, root=root)
    assert rc2 == 1, "second route_cycle must return 1 (ALREADY_ROUTED)"

    # Conviction gate log: trade plan conviction was 8.5, above the 7.0 threshold
    plan = json.loads((run_dir / "30_trade_plan.json").read_text())
    ticket = plan["tickets"][0]
    assert ticket["ticker"] == "RELIANCE"
    assert ticket["conviction"] >= 7.0, "conviction must be at or above threshold"

    # Scan data provenance: confirm the real Friday regime was used
    regime = json.loads((run_dir / "03_market_regime.json").read_text())
    assert regime["setup_count"] == 295, (
        "E2E must use real Friday scan (295 setups), not a stub"
    )
    assert regime["regime"] == "pullback_in_uptrend"
