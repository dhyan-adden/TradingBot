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
        schemas.HoldingsReview: {"reviews": [], "carry_forward": "", "evidence": []},
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


def _root_settings(root):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "settings.yaml").write_text(
        "capital:\n  paper_starting_inr: 100000\n", encoding="utf-8")


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
    _root_settings(tmp_path)  # holdings review reads the book at run_dir's root
    rc = orchestrator._run_reasoning(d, "postclose", "openrouter", 1200, client=StageFakeClient())
    assert rc == 0
    assert json.loads((d / "orders.json").read_text())["orders"] == []
    assert not (d / "30_trade_plan.json").exists()
    assert not (d / "41_pm_decision.json").exists()
    # discovery is gone from postclose; the review ran instead
    assert not (d / "14_shortlist.json").exists()
    assert not (d / "22_debate.json").exists()
    assert (d / "15_holdings_review.json").exists()
    assert (d / "11_sentiment.json").exists()      # postclose keeps the deep read


def test_intraday_runs_pulse_dag_only(tmp_path):
    d = tmp_path / "runs" / "2026-07-14_1400_intraday"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    _root_settings(tmp_path)  # holdings review reads the book at run_dir's root
    rc = orchestrator._run_reasoning(d, "intraday", "openrouter", 1200, client=StageFakeClient())
    assert rc == 0
    assert (d / "10_news.json").exists()
    assert (d / "13_technical.json").exists()
    assert (d / "15_holdings_review.json").exists()
    assert not (d / "11_sentiment.json").exists()   # fundamentals/sentiment do not change intraday
    assert not (d / "12_fundamentals.json").exists()
    assert not (d / "14_shortlist.json").exists()
    assert json.loads((d / "orders.json").read_text())["orders"] == []


def _adhoc_client(required_stages):
    client = StageFakeClient()
    client.DEFAULTS = dict(StageFakeClient.DEFAULTS)
    client.DEFAULTS[schemas.AdhocIntake] = {
        "classification": "ticker_dossier", "safe_interpretation": "research",
        "required_stages": required_stages, "refused_parts": [],
    }
    return client


def test_adhoc_intake_prunes_dag_to_named_artifacts(tmp_path):
    d = _run_dir(tmp_path)
    (d / "user_request.md").write_text("# User Request\n\nresearch RELIANCE\n")
    rc = orchestrator._run_reasoning(d, "adhoc", "openrouter", 1200,
                                     client=_adhoc_client(["10_news.md", "13_technical.md"]))
    assert rc == 0
    assert (d / "10_news.json").exists() and (d / "13_technical.json").exists()
    assert not (d / "22_debate.json").exists()


def test_adhoc_intake_junk_stage_names_fail_loud_not_hollow(tmp_path):
    # live 2026-07-13_1246_adhoc: descriptive stage names silently emptied the
    # DAG and the cycle completed as a clean-looking no-orders run. Junk must
    # now die at schema validation -> REASONING_FAILED, never a hollow success.
    d = _run_dir(tmp_path)
    (d / "user_request.md").write_text("# User Request\n\nresearch RELIANCE\n")
    rc = orchestrator._run_reasoning(d, "adhoc", "openrouter", 1200,
                                     client=_adhoc_client(["news_catalyst_research"]))
    assert rc == -2
    assert (d / "reasoning_error.txt").exists()
    assert not (d / "10_news.json").exists()  # nothing pretended to run


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


class CountingFakeClient(StageFakeClient):
    """StageFakeClient that records which roles were actually billed."""
    def __init__(self):
        self.calls = []

    def call_json(self, role, system, user, schema, model=None):
        self.calls.append(role)
        return super().call_json(role, system, user, schema, model)


def test_resume_skips_completed_stages(tmp_path):
    # A crash/restart must not re-pay for stages whose validated artifact exists.
    d = tmp_path / "runs" / "2026-07-14_1600_postclose"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    _root_settings(tmp_path)
    (d / "10_news.json").write_text(
        json.dumps({"macro_context": "done earlier", "names_in_play": [],
                    "macro_themes": [], "evidence": []}), encoding="utf-8")
    client = CountingFakeClient()
    rc = orchestrator._run_reasoning(d, "postclose", "openrouter", 1200, client=client)
    assert rc == 0
    assert "10_news" not in client.calls                  # skipped, not re-billed
    assert {"11_sentiment", "12_fundamentals", "13_technical",
            "15_holdings_review"} <= set(client.calls)
    # the pre-existing artifact was preserved, not overwritten
    assert json.loads((d / "10_news.json").read_text())["macro_context"] == "done earlier"


def test_resume_reruns_half_written_artifact(tmp_path):
    d = tmp_path / "runs" / "2026-07-14_1600_postclose"
    d.mkdir(parents=True)
    for f in ("00_context.md", "01_news_raw.md", "02_setups_raw.md"):
        (d / f).write_text(f"# {f}\n")
    _root_settings(tmp_path)
    (d / "10_news.json").write_text('{"macro_context": "truncated', encoding="utf-8")
    client = CountingFakeClient()
    rc = orchestrator._run_reasoning(d, "postclose", "openrouter", 1200, client=client)
    assert rc == 0
    assert "10_news" in client.calls   # invalid artifact -> stage re-runs
