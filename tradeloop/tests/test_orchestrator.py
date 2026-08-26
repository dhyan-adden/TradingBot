import importlib
import json
from datetime import date

from tradeloop.lib.util.holidays import NSE_HOLIDAYS_2026, is_nse_holiday


def test_tradeloop_package_is_importable() -> None:
    # tradeloop must be a real importable package (packaging fix), not only
    # reachable via a sys.path hack inside scripts.
    mod = importlib.import_module("tradeloop.lib.broker.paper_broker")
    assert hasattr(mod, "PaperBroker")
    orch = importlib.import_module("tradeloop.orchestrator")
    assert hasattr(orch, "main")


def test_nse_2026_holiday_gate() -> None:
    assert is_nse_holiday(date(2026, 1, 26)) is True   # Republic Day
    assert is_nse_holiday(date(2026, 6, 26)) is True   # Muharram
    assert is_nse_holiday(date(2026, 3, 26)) is True   # Ram Navami (Thu — corrected date)
    assert is_nse_holiday(date(2026, 7, 1)) is False   # ordinary Wednesday
    assert is_nse_holiday(date(2026, 7, 4)) is True    # Saturday — weekend gate
    assert len(NSE_HOLIDAYS_2026) == 16


from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def test_master_prompt_hands_routing_to_python() -> None:
    text = (PROMPTS / "00_master_orchestrator.md").read_text(encoding="utf-8").lower()
    assert "do not route orders" in text
    assert "does not write fills.json" in text or "do not write fills.json" in text


def test_pm_prompt_writes_orders_only_not_fills() -> None:
    text = (PROMPTS / "41_portfolio_manager.md").read_text(encoding="utf-8").lower()
    assert "orders.json" in text
    assert "do not write" in text and "fills.json" in text


from tradeloop import orchestrator
from tradeloop.lib.audit.ledger import Ledger
from tradeloop.lib.config import load_settings
from tradeloop.lib.llm.schemas import PMDecision


def test_run_reasoning_is_a_seam(monkeypatch, tmp_path) -> None:
    calls = {}

    def fake(run_dir, mode, agent, timeout):
        calls["run_dir"] = run_dir
        calls["mode"] = mode
        return 0

    monkeypatch.setattr(orchestrator, "_run_reasoning", fake)
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "codex", 0)
    assert rc == 0
    assert calls["mode"] == "premarket"


def test_opencode_backend_selects_opencode_client(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_dag(run_dir, mode, timeout, client, settings=None, generated_by="", root=None):
        captured["client"] = client
        captured["generated_by"] = generated_by
        return 0

    monkeypatch.setattr(orchestrator, "_run_reasoning_dag", fake_dag)
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "opencode", 1)

    assert rc == 0
    assert captured["client"].__class__.__name__ == "OpenCodeStageClient"
    assert captured["generated_by"] == "tradeloop.reasoning.opencode"


def _fresh_root(tmp_path):
    """Copy the minimal config the orchestrator reads into an isolated root."""
    import shutil
    root = tmp_path / "tradeloop"
    (root / "config").mkdir(parents=True)
    (root / "state").mkdir()
    src = Path(__file__).resolve().parents[1]
    shutil.copy(src / "config" / "settings.yaml", root / "config" / "settings.yaml")
    shutil.copy(src / "config" / "universe.yaml", root / "config" / "universe.yaml")
    return root


def test_holiday_halts_before_reasoning(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    called = {"reasoned": False}
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: called.__setitem__("reasoned", True) or 0)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 1, 26))  # Republic Day
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert called["reasoned"] is False


def test_kill_switch_halts_before_reasoning(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    (root / "kill_switch.md").write_text("halt", encoding="utf-8")
    called = {"reasoned": False}
    monkeypatch.setattr(orchestrator, "_run_reasoning", lambda *a, **k: called.__setitem__("reasoned", True) or 0)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0
    assert called["reasoned"] is False


def test_malformed_orders_aborts_loud(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        (run_dir / "orders.json").write_text("{not json", encoding="utf-8")
        return 0

    def fake_prepare(mode, request="", root=None):
        assert root is not None
        run_dir = root / "runs" / f"test_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 1


def test_uncited_news_candidates_warns_but_never_blocks(monkeypatch, tmp_path, capsys) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        assert root is not None
        run_dir = root / "runs" / f"warn_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        # news-track candidate on the shortlist, yet zero citations anywhere:
        # the one shape the citation tripwire must flag - without failing the run
        (run_dir / "14_shortlist.json").write_text(json.dumps({
            "evidence": [],
            "candidates": [{"ticker": "SBIN", "source_track": "tier_a"}]}),
            encoding="utf-8")
        (run_dir / "orders.json").write_text(json.dumps({"orders": []}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    out = capsys.readouterr().out
    assert rc == 0                                   # heuristic: warn, never block
    assert "tradeloop_warning=UNCITED_NEWS_CANDIDATES" in out
    assert "SBIN" in out
    assert "tradeloop_cycle=AUTO_ROUTING" in out  # default is now auto mode


def test_end_to_end_gate_runs_on_every_order(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        assert root is not None
        run_dir = root / "runs" / f"e2e_{mode}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        # One approved BUY (in universe, >= min_position_size 15000, under the
        # 25% allocation cap of the 100000 starting equity) + one non-universe reject.
        (run_dir / "orders.json").write_text(json.dumps({"orders": [
            {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000, "hard_stop": 950.0,
             "target_1": 1100.0, "strategy_family": "20d_breakout"},
            {"ticker": "FAKECO", "side": "BUY", "quantity": 1, "price": 5000},
        ]}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("premarket", root=root)
    assert rc == 0

    # Auto mode: run_cycle routes immediately, fills.json exists after the call.
    run_dir = root / "runs" / "e2e_premarket"
    fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    statuses = {f.get("status") for f in fills}
    assert "FILLED" in statuses            # approved order routed
    assert "RISK_REJECTED" in statuses     # non-universe order gated
    decisions = (run_dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(decisions) == 2             # gate logged its own verdict per order

    # fills_summary.md must be written as the notification artifact.
    assert (run_dir / "fills_summary.md").exists()

    # Persistence: the FILLED fill (and its hard_stop) reached the ledger, so the
    # NEXT cycle's hydrate sees the position — spec acceptance #3.
    book_path = root / "state" / "ledger.db"
    rehydrated = orchestrator.hydrate(book_path, 100000)
    assert rehydrated.positions == {"RELIANCE": 20}
    fill_events = Ledger(book_path).replay(["paper.order.filled"])
    assert len(fill_events) == 1
    assert fill_events[0]["symbol"] == "RELIANCE" and fill_events[0]["quantity"] == 20
    # Plan data rides the fill event so attribution can score this trade whenever
    # it closes, without needing the closing run's orders.json.
    assert fill_events[0]["hard_stop"] == 950.0
    assert fill_events[0]["target_1"] == 1100.0
    assert fill_events[0]["strategy_family"] == "20d_breakout"

    # Double-routing is still prevented (auto-route already fired).
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 1
    fill_events = Ledger(book_path).replay(["paper.order.filled"])
    assert len(fill_events) == 1  # unchanged


def test_route_respects_kill_switch(monkeypatch, tmp_path) -> None:
    # Kill switch thrown BETWEEN propose and approve must block routing.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = root / "runs" / "ks_premarket"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps({"orders": [
        {"ticker": "RELIANCE", "side": "BUY", "quantity": 20, "price": 1000},
    ]}), encoding="utf-8")
    (root / "kill_switch.md").write_text("halt", encoding="utf-8")
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    assert not (run_dir / "fills.json").exists()  # nothing routed


def test_route_applies_tighten_only_stop_updates(monkeypatch, tmp_path) -> None:
    # Stop updates ride the same approval as orders; tighten-only, held-only.
    # Postclose may tighten (pure risk reduction) even though it fills nothing.
    from tradeloop.lib.audit.ledger import ORDER_FILLED
    from tradeloop.scripts.prepare_cycle import _portfolio_state

    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    led = Ledger(root / "state" / "ledger.db")
    led.append({"type": ORDER_FILLED, "order_id": "X1", "symbol": "HDFCBANK", "side": "BUY",
                "quantity": 30, "fill_price": 830.62, "product": "CNC", "hard_stop": 807.24})
    run_dir = root / "runs" / "2026-07-14_1600_postclose"
    run_dir.mkdir(parents=True)
    (run_dir / "orders.json").write_text(json.dumps(
        {"mode": "postclose", "live_orders_enabled": False,
         "generated_by": "test", "orders": [], "held": []}), encoding="utf-8")
    (run_dir / "stop_updates.json").write_text(json.dumps(
        {"HDFCBANK": 820.0, "GHOST": 50.0}), encoding="utf-8")

    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    state = _portfolio_state(root)
    assert state.hard_stops["HDFCBANK"] == 820.0     # tightened
    assert "GHOST" not in state.hard_stops           # unheld symbol ignored

    # loosening attempt is a no-op (fills.json stays [], so re-route is allowed)
    (run_dir / "stop_updates.json").write_text(json.dumps({"HDFCBANK": 700.0}), encoding="utf-8")
    rc = orchestrator.route_cycle(run_dir, root=root)
    assert rc == 0
    assert _portfolio_state(root).hard_stops["HDFCBANK"] == 820.0


def test_manager_backchannel_retry_uses_strongest_model_and_applies_revised_orders(tmp_path) -> None:
    root = _fresh_root(tmp_path)
    run_dir = root / "runs" / "2026-08-24_0918_premarket"
    run_dir.mkdir(parents=True)
    (run_dir / "03_market_regime.md").write_text("# Regime\nreduced-risk range bound\n", encoding="utf-8")
    (run_dir / "30_trade_plan.json").write_text(json.dumps({
        "evidence": [],
        "tickets": [
            {
                "ticker": "LTFOODS", "side": "BUY", "product": "CNC",
                "strategy_family": "20d_breakout", "entry": 466.5,
                "hard_stop": 447.17, "target_1": 505.17, "target_2": 524.5,
                "quantity": 51, "time_horizon": "3-10 days",
                "thesis": "low-conviction setup", "conviction": 6.0,
            },
            {
                "ticker": "TCS", "side": "BUY", "product": "CNC",
                "strategy_family": "20d_breakout", "entry": 4100.0,
                "hard_stop": 3940.0, "target_1": 4400.0, "target_2": 4550.0,
                "quantity": 4, "time_horizon": "5-20 days",
                "thesis": "stronger alternate", "conviction": 7.4,
            },
        ],
    }), encoding="utf-8")
    (run_dir / "30_trade_plan.md").write_text("# 30_trade_plan\n", encoding="utf-8")
    (run_dir / "40_risk_report.md").write_text("# 40_risk_report\n", encoding="utf-8")
    (run_dir / "41_pm_decision.md").write_text("# 41_pm_decision\n", encoding="utf-8")
    (run_dir / "orders.json").write_text(json.dumps({
        "mode": "premarket",
        "live_orders_enabled": False,
        "generated_by": "tradeloop.reasoning.opencode",
        "orders": [
            {
                "ticker": "LTFOODS", "side": "BUY", "product": "CNC",
                "quantity": 51, "price": 466.5, "order_type": "LIMIT",
                "hard_stop": 447.17, "target_1": 505.17, "target_2": 524.5,
                "max_entry_price": 466.5, "strategy_family": "20d_breakout",
                "status": "APPROVED", "reason": "initial pm decision",
            }
        ],
        "held": [],
    }), encoding="utf-8")

    class FakeClient:
        def __init__(self):
            self.model = ""

        def call_json(self, role, system, user, schema, model=None, max_tokens=None):
            self.model = model or ""
            return PMDecision.model_validate({
                "evidence": [],
                "orders": [
                    {
                        "ticker": "TCS", "side": "BUY", "product": "CNC",
                        "quantity": 4, "price": 4100.0, "order_type": "LIMIT",
                        "hard_stop": 3940.0, "target_1": 4400.0, "target_2": 4550.0,
                        "max_entry_price": 4100.0, "strategy_family": "20d_breakout",
                        "status": "APPROVED", "reason": "drop low-conviction LTFOODS",
                    }
                ],
                "held": [],
            })

    client = FakeClient()
    settings = load_settings(root / "config" / "settings.yaml")

    applied, retry_reason = orchestrator._manager_backchannel_retry(
        run_dir,
        mode="premarket",
        backend="opencode",
        settings=settings,
        client=client,
    )

    assert applied is True
    assert retry_reason is None
    assert client.model == "openai/gpt-5.6-luna"
    orders = json.loads((run_dir / "orders.json").read_text(encoding="utf-8"))
    assert orders["orders"][0]["ticker"] == "TCS"
    assert orders["generated_by"].endswith(".manager_backchannel")
    backchannel = json.loads((run_dir / "42_manager_backchannel.json").read_text(encoding="utf-8"))
    assert backchannel["status"] == "applied"


def test_conviction_block_records_manager_feedback(monkeypatch, tmp_path, capsys) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def fake_prepare(mode, request="", root=None):
        assert root is not None
        run_dir = root / "runs" / "conviction_feedback"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def fake_reason(run_dir, mode, agent, timeout, **kwargs):
        (run_dir / "30_trade_plan.json").write_text(json.dumps({
            "evidence": [],
            "tickets": [{
                "ticker": "LTFOODS", "side": "BUY", "product": "CNC",
                "strategy_family": "20d_breakout", "entry": 466.5,
                "hard_stop": 447.17, "target_1": 505.17, "target_2": 524.5,
                "quantity": 51, "time_horizon": "3-10 days",
                "thesis": "low conviction", "conviction": 6.0,
            }],
        }), encoding="utf-8")
        (run_dir / "orders.json").write_text(json.dumps({
            "mode": mode,
            "live_orders_enabled": False,
            "generated_by": "tradeloop.reasoning.opencode",
            "orders": [{
                "ticker": "LTFOODS", "side": "BUY", "product": "CNC",
                "quantity": 51, "price": 466.5, "order_type": "LIMIT",
                "hard_stop": 447.17, "target_1": 505.17, "target_2": 524.5,
                "strategy_family": "20d_breakout", "reason": "initial decision",
            }],
            "held": [],
        }), encoding="utf-8")
        return 0

    class FakeClient:
        def call_json(self, role, system, user, schema, model=None, max_tokens=None):
            return PMDecision.model_validate({
                "evidence": [],
                "orders": [{
                    "ticker": "LTFOODS", "side": "BUY", "product": "CNC",
                    "quantity": 51, "price": 466.5, "order_type": "LIMIT",
                    "hard_stop": 447.17, "target_1": 505.17, "target_2": 524.5,
                    "strategy_family": "20d_breakout", "reason": "still low conviction",
                }],
                "held": [],
            })

    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    monkeypatch.setattr(orchestrator, "_make_stage_client", lambda backend, run_dir: FakeClient())

    rc = orchestrator.run_cycle("premarket", root=root, backend="opencode")
    assert rc == 1
    feedback = (root / "memory" / "manager_feedback.md").read_text(encoding="utf-8")
    assert "conviction_gate_blocked" in feedback
    assert "LTFOODS" in feedback
    assert "still_blocked" in feedback


def test_route_cycle_manager_retry_can_shrink_oversized_order(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = root / "runs" / "route_retry"
    run_dir.mkdir(parents=True)
    (run_dir / "30_trade_plan.json").write_text(json.dumps({
        "evidence": [],
        "tickets": [{
            "ticker": "TCS", "side": "BUY", "product": "CNC",
            "strategy_family": "20d_breakout", "entry": 3000.0,
            "hard_stop": 2850.0, "target_1": 3250.0, "target_2": 3400.0,
            "quantity": 100, "time_horizon": "5-20 days",
            "thesis": "strong setup", "conviction": 8.0,
        }],
    }), encoding="utf-8")
    for name in ("30_trade_plan.md", "40_risk_report.md", "41_pm_decision.md", "03_market_regime.md"):
        (run_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (run_dir / "orders.json").write_text(json.dumps({
        "mode": "premarket",
        "live_orders_enabled": False,
        "generated_by": "tradeloop.reasoning.opencode",
        "orders": [{
            "ticker": "TCS", "side": "BUY", "product": "CNC",
            "quantity": 100, "price": 3000.0, "order_type": "LIMIT",
            "hard_stop": 2850.0, "target_1": 3250.0, "target_2": 3400.0,
            "strategy_family": "20d_breakout", "reason": "oversized test",
        }],
        "held": [],
    }), encoding="utf-8")

    class FakeClient:
        def __init__(self):
            self.model = ""

        def call_json(self, role, system, user, schema, model=None, max_tokens=None):
            self.model = model or ""
            return PMDecision.model_validate({
                "evidence": [],
                "orders": [{
                    "ticker": "TCS", "side": "BUY", "product": "CNC",
                    "quantity": 8, "price": 3000.0, "order_type": "LIMIT",
                    "hard_stop": 2850.0, "target_1": 3250.0, "target_2": 3400.0,
                    "strategy_family": "20d_breakout", "reason": "reduce to fit cap",
                }],
                "held": [],
            })

    client = FakeClient()
    monkeypatch.setattr(orchestrator, "_make_stage_client", lambda backend, run_dir: client)

    rc = orchestrator.route_cycle(run_dir, root=root)

    assert rc == 0
    assert client.model == "openai/gpt-5.6-luna"
    fills = json.loads((run_dir / "fills.json").read_text(encoding="utf-8"))
    assert fills[0]["status"] == "FILLED"
    assert fills[0]["payload"]["quantity"] == 8
    backchannel = json.loads((run_dir / "42_manager_backchannel.json").read_text(encoding="utf-8"))
    assert backchannel["event"] == "route_risk_rejected"
    assert backchannel["status"] == "applied"
    feedback = (root / "memory" / "manager_feedback.md").read_text(encoding="utf-8")
    assert "route_outcome" in feedback
    assert "manager_retry_status: applied" in feedback
    assert "final_status: FILLED" in feedback


def test_run_cycle_resumes_existing_run_dir_without_prepare(monkeypatch, tmp_path) -> None:
    # --run-dir: a killed cycle is completed in place; prepare must NOT run
    # (a new run dir would re-bill every stage).
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = root / "runs" / "2026-07-14_1600_postclose"
    run_dir.mkdir(parents=True)

    def exploding_prepare(mode, request="", root=None):
        raise AssertionError("prepare must not run on resume")

    def fake_reason(rd, mode, agent, timeout, **kwargs):
        (rd / "orders.json").write_text(json.dumps(
            {"mode": mode, "live_orders_enabled": False, "generated_by": "test",
             "orders": [], "held": []}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orchestrator, "_prepare", exploding_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    rc = orchestrator.run_cycle("postclose", root=root, run_dir=run_dir)
    assert rc == 0


def test_run_cycle_rejects_mode_mismatched_run_dir(monkeypatch, tmp_path) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))
    run_dir = root / "runs" / "2026-07-14_1600_postclose"
    run_dir.mkdir(parents=True)
    rc = orchestrator.run_cycle("premarket", root=root, run_dir=run_dir)
    assert rc == 2


def test_holdings_modes_skip_on_empty_book(monkeypatch, tmp_path, capsys) -> None:
    # No holdings -> intraday/postclose have nothing to review; the cycle must
    # skip BEFORE prepare/scan/LLM so an empty book costs zero tokens.
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(orchestrator, "_today", lambda: date(2026, 7, 1))

    def exploding(*a, **k):
        raise AssertionError("must not run on an empty book")
    monkeypatch.setattr(orchestrator, "_prepare", exploding)
    monkeypatch.setattr(orchestrator, "_run_reasoning", exploding)

    for mode in ("intraday", "postclose"):
        rc = orchestrator.run_cycle(mode, root=root)
        assert rc == 0
        assert "tradeloop_cycle=SKIP reason=no_holdings" in capsys.readouterr().out

    # premarket must NOT be gated on holdings (discovery is its whole job)
    def fake_reason(rd, mode, agent, timeout, **kwargs):
        (rd / "orders.json").write_text(json.dumps(
            {"mode": mode, "live_orders_enabled": False, "generated_by": "test",
             "orders": [], "held": []}), encoding="utf-8")
        return 0

    def fake_prepare(mode, request="", root=None):
        assert root is not None
        d = root / "runs" / f"empty_{mode}"
        d.mkdir(parents=True, exist_ok=True)
        return d
    monkeypatch.setattr(orchestrator, "_prepare", fake_prepare)
    monkeypatch.setattr(orchestrator, "_run_reasoning", fake_reason)
    assert orchestrator.run_cycle("premarket", root=root) == 0
