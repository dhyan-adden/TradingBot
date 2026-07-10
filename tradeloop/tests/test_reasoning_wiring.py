import json
from pathlib import Path

from tradeloop import orchestrator
from tradeloop.lib.llm import schemas


class StageFakeClient:
    """Returns a minimal valid object for whatever stage schema is requested."""
    DEFAULTS = {
        schemas.NewsAnalysis: {"names_in_play": [], "evidence": []},
        schemas.SentimentReport: {"scores": [], "evidence": []},
        schemas.FundamentalsReport: {"tags": [], "evidence": []},
        schemas.TechnicalReport: {"setups": [], "evidence": []},
        schemas.Shortlist: {"candidates": [], "evidence": []},
        schemas.BullCase: {"arguments": [], "evidence": []},
        schemas.BearCase: {"arguments": [], "evidence": []},
        schemas.Debate: {"names": [], "evidence": []},
        schemas.TradePlan: {"tickets": [], "evidence": []},
        schemas.RiskReport: {"decisions": [], "evidence": []},
        schemas.PMDecision: {
            "orders": [{"ticker": "RELIANCE", "side": "BUY", "product": "CNC",
                        "quantity": 8, "price": 2500.0, "order_type": "LIMIT",
                        "reason": "approved"}],
            "held": [], "evidence": ["a1b2c3d4e5f6"],
        },
    }

    def call_json(self, role, system, user, schema, model=None):
        return schema.model_validate(self.DEFAULTS[schema])


def _run_dir(tmp_path):
    d = tmp_path / "runs" / "2026-07-02_0800_premarket"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    return d


def test_openrouter_backend_runs_dag_and_python_writes_orders_json(tmp_path):
    d = _run_dir(tmp_path)
    rc = orchestrator._run_reasoning(d, "premarket", "openrouter", 1200, client=StageFakeClient())
    assert rc == 0
    orders = json.loads((d / "orders.json").read_text())
    assert orders["mode"] == "premarket"
    assert orders["live_orders_enabled"] is False
    assert orders["orders"][0]["ticker"] == "RELIANCE"
    assert orders["orders"][0]["side"] == "BUY"
    # PM stage artifact was validated and written
    assert (d / "41_pm_decision.json").exists()


def test_postclose_skips_trade_stages_and_proposes_nothing(tmp_path):
    # postclose = no trading: the DAG must not run trader/risk/PM, so orders=[] even
    # though the fake PM would return a BUY. Regresses the 2026-07-07 mode-blind DAG.
    d = tmp_path / "runs" / "2026-07-07_1600_postclose"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    rc = orchestrator._run_reasoning(d, "postclose", "openrouter", 1200, client=StageFakeClient())
    assert rc == 0
    assert json.loads((d / "orders.json").read_text())["orders"] == []
    assert not (d / "30_trade_plan.json").exists()
    assert not (d / "41_pm_decision.json").exists()


def test_claude_backend_dispatches_to_subagent_subprocess(tmp_path, monkeypatch):
    # The default backend must reason via the Claude Code subagent subprocess
    # (run_cycle.sh claude path), NOT the in-process OpenRouter DAG.
    captured = {}

    def fake_run(argv, env=None, cwd=None, timeout=None):
        captured["argv"] = argv
        captured["env"] = env

        class Proc:
            returncode = 0

        return Proc()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    rc = orchestrator._run_reasoning(tmp_path, "premarket", "claude", 5)
    assert rc == 0
    assert captured["argv"][2] == "premarket"
    assert captured["env"]["TRADELOOP_AGENT"] == "claude"        # subscription path
    assert captured["env"]["TRADELOOP_RUN_DIR"] == str(tmp_path)  # pinned run dir
    # in-process DAG must NOT have run under the claude backend
    assert not (tmp_path / "orders.json").exists()


def test_unknown_backend_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        orchestrator._run_reasoning(tmp_path, "premarket", "codex", 5)


def _claude_run_writing(tmp_path, monkeypatch, orders_json_text):
    """Run the claude backend with the subagent spawn stubbed out by a fake that
    writes exactly what the real PM subagent writes to orders.json - the legacy
    bare-array shape from output_schemas.md - then return the pinned run dir."""
    d = tmp_path / "runs" / "2026-07-09_1129_premarket"
    d.mkdir(parents=True)
    (d / "orders.json").write_text("[]\n")  # prepare_cycle's placeholder

    def fake_run(argv, env=None, cwd=None, timeout=None):
        Path(env["TRADELOOP_RUN_DIR"], "orders.json").write_text(orders_json_text)

        class Proc:
            returncode = 0

        return Proc()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    rc = orchestrator._run_reasoning(d, "premarket", "claude", 5)
    assert rc == 0
    return d


def test_claude_hold_is_canonical_dict_not_still_running(tmp_path, monkeypatch):
    # E2E of the "why no decision yet?" bug: a Claude HOLD writes the bare array
    # `[]`, which the dashboard read as IN_FLIGHT ("Still running - no decision yet").
    # After the fix the backend normalises it to the canonical dict so the finished
    # run reads as a clean hold.
    from tradeloop.dashboard.runs import IN_FLIGHT, read_run

    d = _claude_run_writing(tmp_path, monkeypatch, "[]\n")

    orders = json.loads((d / "orders.json").read_text())
    assert isinstance(orders, dict) and orders["orders"] == []       # canonical, not bare []
    assert orders["generated_by"] == "tradeloop.reasoning.claude"
    view = read_run(d)
    assert view["live"] is False                                     # finished, not in-flight
    assert view["decision"]["summary"] != IN_FLIGHT
    assert "Holding today" in view["decision"]["summary"]


def test_claude_buy_renders_and_does_not_crash_dashboard(tmp_path, monkeypatch):
    # A Claude BUY writes a bare `[{...}]`; render_decision's `.get("orders")` would
    # crash on a list. After the fix it's a dict, the dashboard renders the proposal,
    # and the deterministic router still parses the order.
    from tradeloop.dashboard.runs import read_run
    from tradeloop.lib.broker.orders_schema import load_orders

    bare = json.dumps([{"ticker": "SUNPHARMA", "side": "BUY", "product": "CNC",
                        "quantity": 5, "price": 1937.30, "order_type": "LIMIT",
                        "hard_stop": 1886.55, "reason": "PM approved"}])
    d = _claude_run_writing(tmp_path, monkeypatch, bare)

    orders = json.loads((d / "orders.json").read_text())
    assert isinstance(orders, dict) and orders["orders"][0]["ticker"] == "SUNPHARMA"
    view = read_run(d)                                               # must not raise
    assert view["live"] is False
    assert "SUNPHARMA" in view["decision"]["summary"] or "Sun" in view["decision"]["summary"]
    # router-side contract intact
    assert load_orders(d / "orders.json").orders[0].ticker == "SUNPHARMA"
