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
