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


def test_claude_backend_runs_dag_in_process(tmp_path):
    # The claude backend now runs the SAME deterministic DAG as openrouter, with a
    # ClaudeStageClient. With an injected fake client it must produce the canonical
    # Python-owned orders.json dict, stamped as the claude reasoning path.
    d = _run_dir(tmp_path)
    rc = orchestrator._run_reasoning(d, "premarket", "claude", 1200, client=StageFakeClient())
    assert rc == 0
    orders = json.loads((d / "orders.json").read_text())
    assert isinstance(orders, dict)
    assert orders["generated_by"] == "tradeloop.reasoning.claude"
    assert orders["orders"][0]["ticker"] == "RELIANCE"
    assert (d / "41_pm_decision.json").exists()


def test_unknown_backend_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        orchestrator._run_reasoning(tmp_path, "premarket", "codex", 5)
