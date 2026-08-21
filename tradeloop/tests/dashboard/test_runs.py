import json
from pathlib import Path

from tradeloop.dashboard.runs import list_runs, read_run


def _make_run(runs_dir: Path, name: str, with_decision: bool):
    d = runs_dir / name
    d.mkdir(parents=True)
    (d / "10_news.json").write_text(json.dumps(
        {"names_in_play": [{"ticker": "HDFCBANK", "catalyst": "Q1", "tier": "A"}]}))
    if with_decision:
        (d / "41_pm_decision.json").write_text(json.dumps({"orders": [], "held": []}))
        (d / "orders.json").write_text(json.dumps({"orders": [], "held": []}))
    return d


def test_list_runs_newest_first(tmp_path):
    _make_run(tmp_path, "2026-07-03_0900_premarket", True)
    _make_run(tmp_path, "2026-07-04_0900_premarket", True)
    runs = list_runs(tmp_path)
    assert [r.dir_name for r in runs][0] == "2026-07-04_0900_premarket"
    assert runs[0].mode == "premarket"


def test_read_run_complete_has_stages_and_decision(tmp_path):
    d = _make_run(tmp_path, "2026-07-04_0900_premarket", True)
    out = read_run(d)
    assert out["live"] is False
    stages = {s["stage"] for s in out["stages"]}
    assert "10_news" in stages
    assert out["decision"]["summary"]


def test_read_run_debate_card_includes_bull_and_bear_arguments(tmp_path):
    d = _make_run(tmp_path, "2026-07-13_1330_adhoc", True)
    (d / "20_bull.json").write_text(json.dumps(
        {"arguments": [{"ticker": "UTIAMC", "claim": "volume-confirmed"}]}))
    (d / "21_bear.json").write_text(json.dumps(
        {"arguments": [{"ticker": "UTIAMC", "claim": "beta rally"}]}))
    (d / "22_debate.json").write_text(json.dumps(
        {"names": [{"ticker": "UTIAMC", "conviction": 6.0, "verdict": "tradeable"}]}))
    debate = [s for s in read_run(d)["stages"] if s["stage"] == "22_debate"][0]
    assert "For: volume-confirmed" in debate["points"]
    assert "Against: beta rally" in debate["points"]


def test_read_run_live_when_no_decision(tmp_path):
    d = _make_run(tmp_path, "2026-07-04_0900_premarket", False)
    out = read_run(d)
    assert out["live"] is True


def test_read_run_surfaces_reasoning_failure_not_a_hold(tmp_path):
    d = tmp_path / "2026-07-06_1319_premarket"
    d.mkdir()
    (d / "10_news.json").write_text(json.dumps({"names_in_play": []}))
    (d / "orders.json").write_text(json.dumps({"orders": [], "held": []}))  # placeholder
    (d / "reasoning_error.txt").write_text("reasoning failed at 13_technical: empty content\n")
    out = read_run(d)
    assert out["error"]
    assert out["live"] is False                      # failed, not "still running"
    assert "did not finish" in out["decision"]["summary"]
    assert "Holding" not in out["decision"]["summary"]
    runs = list_runs(tmp_path)                       # dropdown must not lie either
    assert "Holding" not in runs[0].decision


def test_read_run_in_flight_not_a_hold(tmp_path):
    # regression (live 2026-07-08): an IN-FLIGHT run (no PM decision yet, orders.json
    # still prepare's empty placeholder) rendered a confident "Holding today" on the
    # decision card - a lie while the scan/reasoning is still running.
    d = _make_run(tmp_path, "2026-07-08_1312_intraday", False)
    (d / "orders.json").write_text("[]")             # prepare's placeholder
    out = read_run(d)
    assert out["live"] is True
    assert "Holding" not in out["decision"]["summary"]
    assert "till running" in out["decision"]["summary"]  # "Still running..."


def test_list_runs_in_flight_not_a_hold(tmp_path):
    # the run-history dropdown showed the same false "Holding today" for a live run
    d = _make_run(tmp_path, "2026-07-08_1312_intraday", False)
    (d / "orders.json").write_text("[]")
    runs = list_runs(tmp_path)
    assert "Holding" not in runs[0].decision
    assert "till running" in runs[0].decision


def test_completed_intraday_run_is_not_still_running(tmp_path):
    # intraday/postclose skip the PM stage, so 41_pm_decision.json NEVER exists for
    # them; the real end-of-run marker is the orders.json dict _run_reasoning writes
    # (prepare's placeholder is the list []). A finished intraday run must read as
    # a decision, not as perpetually "Still running".
    d = _make_run(tmp_path, "2026-07-08_1312_intraday", False)
    (d / "orders.json").write_text(json.dumps(
        {"mode": "intraday", "generated_by": "tradeloop.reasoning.p1",
         "orders": [], "held": []}))
    out = read_run(d)
    assert out["live"] is False
    assert "till running" not in out["decision"]["summary"]
    runs = list_runs(tmp_path)
    assert "till running" not in runs[0].decision


def test_read_run_handles_codex_list_orders_json(tmp_path):
    # regression (live 2026-08-19): the Codex/OpenRouter path writes orders.json as
    # a bare list of orders, not the dict {"orders": [...]} the deterministic router
    # writes. render_decision must not crash on the list form.
    d = _make_run(tmp_path, "2026-08-19_1610_premarket", False)
    (d / "orders.json").write_text(json.dumps([
        {"ticker": "CDSL", "side": "SELL", "quantity": 11, "price": None,
         "reason": "stop_breach"},
        {"ticker": "HDFCBANK", "side": "SELL", "quantity": 30, "price": None,
         "reason": "stop_breach"},
    ]))
    out = read_run(d)
    assert out["live"] is False
    assert "Proposing to SELL 11" in out["decision"]["summary"]
    runs = list_runs(tmp_path)
    assert "Proposing to SELL 11" in runs[0].decision


def test_read_run_renders_codex_markdown_stage(tmp_path):
    d = _make_run(tmp_path, "2026-08-19_1610_premarket", False)
    (d / "10_news.json").unlink()
    (d / "10_news.md").write_text("""# 10_news.md

## Macro context
- Risk-off oil tape persists.
- INR remains soft.
""")
    out = read_run(d)
    news = next(stage for stage in out["stages"] if stage["stage"] == "10_news")
    assert news["title"] == "News Expert"
    assert news["summary"] == "Risk-off oil tape persists."
    assert "INR remains soft." in news["points"]


def test_stage_cards_show_the_model_that_actually_ran(tmp_path):
    # regression: the dashboard labelled cards from the OpenRouter routing config,
    # so a clean claude-backend run still showed "MiMo v2.5" / "MiniMax M3". The
    # badge must come from the run's audit log = what really ran.
    d = _make_run(tmp_path, "2026-07-10_1606_premarket", True)
    (d / "22_debate.json").write_text(json.dumps({"names": []}))
    (d / "llm_calls.jsonl").write_text(
        json.dumps({"role": "10_news", "model": "claude:sonnet", "used_model": True}) + "\n"
        + json.dumps({"role": "22_debate", "model": "claude:opus", "used_model": True}) + "\n")
    out = read_run(d)
    by_stage = {s["stage"]: s["model"] for s in out["stages"]}
    assert by_stage["10_news"] == "Claude Sonnet"
    assert by_stage["22_debate"] == "Claude Opus"


def test_read_run_aggregates_llm_usage_and_cost(tmp_path):
    d = _make_run(tmp_path, "2026-07-10_1606_premarket", True)
    (d / "llm_calls.jsonl").write_text(
        json.dumps({"role": "10_news", "used_model": True, "prompt_tokens": 100,
                    "completion_tokens": 20, "total_tokens": 120,
                    "cost_usd": 0.001, "cost_known": True}) + "\n"
        + json.dumps({"role": "10_news", "used_model": False, "prompt_tokens": 0,
                      "completion_tokens": 0, "total_tokens": 0,
                      "cost_usd": 0.0, "cost_known": False}) + "\n")
    usage = read_run(d)["usage"]
    assert usage["calls"] == 2
    assert usage["successful_calls"] == 1
    assert usage["failed_calls"] == 1
    assert usage["total_tokens"] == 120
    assert usage["cost_usd"] == 0.001
    assert usage["cost_known"] is True
    assert usage["by_stage"]["10_news"]["calls"] == 2


def test_read_run_includes_codex_usage(tmp_path):
    d = _make_run(tmp_path, "2026-07-10_1606_premarket", True)
    (d / "codex_usage.json").write_text(json.dumps({
        "calls": 1, "successful_calls": 1, "failed_calls": 0,
        "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
        "cost_usd": 0.002, "cost_known": True,
        "cost_source": "estimated_openrouter_pricing",
    }))
    usage = read_run(d)["usage"]
    assert usage["calls"] == 1
    assert usage["total_tokens"] == 150
    assert usage["cost_usd"] == 0.002
    assert usage["cost_source"] == "estimated_openrouter_pricing"
    assert usage["by_stage"]["codex_orchestrator"]["total_tokens"] == 150


def test_read_run_recovers_legacy_codex_log_usage(tmp_path):
    runs_root = tmp_path / "tradeloop" / "runs"
    d = _make_run(runs_root, "2026-08-19_1610_premarket", False)
    (d / "10_news.json").unlink()
    (d / "10_news.md").write_text("# News\n\n## Macro\n- Risk-off.\n")
    logs = d.parents[1] / "reports" / "cycle_logs"
    logs.mkdir(parents=True)
    (logs / "cycle.log").write_text(
        f"Prepared run directory: {d}\nmodel: minimax/minimax-m3\n\n"
        "tokens used\n244,512\n")
    usage = read_run(d)["usage"]
    assert usage["calls"] == 1
    assert usage["total_tokens"] == 244512
    assert usage["cost_known"] is False
    assert usage["by_stage"]["codex_orchestrator"]["handoffs"] == 1
    news = next(stage for stage in read_run(d)["stages"] if stage["stage"] == "10_news")
    assert news["model"] == "Codex / MiniMax M3"


def test_failed_attempt_does_not_override_the_model_that_succeeded(tmp_path):
    # audit logs a failed try then the successful call for the same role; the badge
    # must name the model that actually produced the output.
    d = _make_run(tmp_path, "2026-07-10_1606_premarket", True)
    (d / "llm_calls.jsonl").write_text(
        json.dumps({"role": "10_news", "model": "claude:sonnet", "used_model": False}) + "\n"
        + json.dumps({"role": "10_news", "model": "claude:opus", "used_model": True}) + "\n")
    out = read_run(d)
    assert {s["stage"]: s["model"] for s in out["stages"]}["10_news"] == "Claude Opus"


def test_read_run_tolerates_missing_and_malformed_files(tmp_path):
    d = tmp_path / "2026-07-04_0900_premarket"
    d.mkdir()
    (d / "10_news.json").write_text("{ this is not json")
    out = read_run(d)  # must not raise
    assert isinstance(out["stages"], list)
