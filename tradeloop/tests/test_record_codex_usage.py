import json

from tradeloop.scripts.record_codex_usage import main


def test_records_estimated_cost_from_codex_usage(tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({
        "type": "turn.completed",
        "usage": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
    }) + "\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr("sys.argv", [
        "record_codex_usage.py", "--run-dir", str(run_dir), "--events", str(events),
    ])
    assert main() == 0
    output = json.loads((run_dir / "codex_usage.json").read_text())
    assert output["total_tokens"] == 1500
    assert output["cost_known"] is True
    assert output["cost_source"] == "estimated_openrouter_pricing"
