import json
import types

from tradeloop.lib.llm import opencode_client
from tradeloop.lib.llm.opencode_client import OpenCodeStageClient
from tradeloop.lib.llm.schemas import Shortlist


GOOD_SHORTLIST = {
    "candidates": [{
        "ticker": "RELIANCE",
        "catalyst_type": "earnings",
        "source_track": "tier_a",
        "composite_score": 7.5,
        "thesis": "beat",
        "horizon": "5-20 days",
        "evidence": ["a1b2c3d4e5f6"],
    }],
    "evidence": ["a1b2c3d4e5f6"],
}


def _event(text: str, model: str = "openai/gpt-5.5") -> str:
    return json.dumps({
        "id": "evt_1",
        "model": model,
        "message": {"content": text},
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }) + "\n"


def test_low_stakes_stage_tries_free_zen_model_first(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        model = argv[argv.index("--model") + 1]
        calls.append(model)
        return types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=_event(json.dumps(GOOD_SHORTLIST), model=model),
        )

    monkeypatch.setattr(opencode_client.subprocess, "run", fake_run)
    client = OpenCodeStageClient(
        audit_path=tmp_path / "llm_calls.jsonl",
        max_retries=1,
        backoff_base=0.0,
        cwd=tmp_path,
    )

    out = client.call_json("10_news", "system", "user", Shortlist)

    assert isinstance(out, Shortlist)
    assert calls == ["opencode/nemotron-3-ultra-free"]


def test_pm_decision_falls_back_to_bedrock_glm_when_openai_model_fails(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        model = argv[argv.index("--model") + 1]
        calls.append(model)
        if model == "openai/gpt-5.5":
            return types.SimpleNamespace(returncode=1, stderr="subscription limit", stdout="")
        return types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=_event(json.dumps(GOOD_SHORTLIST), model=model),
        )

    monkeypatch.setattr(opencode_client.subprocess, "run", fake_run)
    client = OpenCodeStageClient(
        audit_path=tmp_path / "llm_calls.jsonl",
        max_retries=1,
        backoff_base=0.0,
        cwd=tmp_path,
    )

    out = client.call_json("41_pm_decision", "system", "user", Shortlist)

    assert isinstance(out, Shortlist)
    assert calls == ["openai/gpt-5.5", "amazon-bedrock/zai.glm-5"]
    records = [json.loads(line) for line in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]
    assert records[0]["used_model"] is False
    assert records[-1]["model"] == "opencode:amazon-bedrock/zai.glm-5"


def test_pm_decision_uses_second_bedrock_fallback_when_glm_fails(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        model = argv[argv.index("--model") + 1]
        calls.append(model)
        if model in ("openai/gpt-5.5", "amazon-bedrock/zai.glm-5"):
            return types.SimpleNamespace(returncode=1, stderr="limit", stdout="")
        return types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=_event(json.dumps(GOOD_SHORTLIST), model=model),
        )

    monkeypatch.setattr(opencode_client.subprocess, "run", fake_run)
    client = OpenCodeStageClient(
        audit_path=tmp_path / "llm_calls.jsonl",
        max_retries=1,
        backoff_base=0.0,
        cwd=tmp_path,
    )

    out = client.call_json("41_pm_decision", "system", "user", Shortlist)

    assert isinstance(out, Shortlist)
    assert calls == [
        "openai/gpt-5.5",
        "amazon-bedrock/zai.glm-5",
        "amazon-bedrock/moonshotai.kimi-k2.5",
    ]
    records = [json.loads(line) for line in (tmp_path / "llm_calls.jsonl").read_text().splitlines()]
    assert records[-1]["model"] == "opencode:amazon-bedrock/moonshotai.kimi-k2.5"


def test_explicit_fallback_models_override_per_stage_chain(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        model = argv[argv.index("--model") + 1]
        calls.append(model)
        if model == "openai/gpt-5.5":
            return types.SimpleNamespace(returncode=1, stderr="limit", stdout="")
        return types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=_event(json.dumps(GOOD_SHORTLIST), model=model),
        )

    monkeypatch.setattr(opencode_client.subprocess, "run", fake_run)
    client = OpenCodeStageClient(
        audit_path=tmp_path / "llm_calls.jsonl",
        fallback_models=("openrouter/xiaomi/mimo-v2.5",),
        max_retries=1,
        backoff_base=0.0,
        cwd=tmp_path,
    )

    out = client.call_json("41_pm_decision", "system", "user", Shortlist)

    assert isinstance(out, Shortlist)
    assert calls == ["openai/gpt-5.5", "openrouter/xiaomi/mimo-v2.5"]


def test_all_models_exhausted_raises_validation_error(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        return types.SimpleNamespace(returncode=1, stderr="limit", stdout="")

    monkeypatch.setattr(opencode_client.subprocess, "run", fake_run)
    client = OpenCodeStageClient(
        audit_path=tmp_path / "llm_calls.jsonl",
        max_retries=1,
        backoff_base=0.0,
        cwd=tmp_path,
    )

    try:
        client.call_json("41_pm_decision", "system", "user", Shortlist)
        raised = False
    except opencode_client.LLMValidationError:
        raised = True
    assert raised


def test_extract_opencode_text_handles_json_event_parts():
    stdout = json.dumps({
        "type": "message",
        "message": {"parts": [{"type": "text", "text": json.dumps(GOOD_SHORTLIST)}]},
    }) + "\n"

    assert json.loads(opencode_client._extract_opencode_text(stdout))["candidates"][0]["ticker"] == "RELIANCE"


def test_extract_opencode_text_handles_real_text_event_shape():
    stdout = "\n".join(json.dumps(evt) for evt in [
        {"type": "step_start", "sessionID": "ses_1",
         "part": {"id": "p1", "type": "step-start", "snapshot": "abc"}},
        {"type": "text", "sessionID": "ses_1",
         "part": {"id": "p2", "type": "text", "text": json.dumps(GOOD_SHORTLIST)}},
        {"type": "step_finish", "sessionID": "ses_1",
         "part": {"id": "p3", "type": "step-finish", "reason": "stop"}},
    ]) + "\n"

    assert json.loads(opencode_client._extract_opencode_text(stdout))["candidates"][0]["ticker"] == "RELIANCE"


def test_extract_opencode_text_ignores_metadata_strings_without_json():
    stdout = json.dumps({
        "type": "step_start",
        "part": {"id": "prt_abc", "sessionID": "ses_1", "type": "step-start",
                 "snapshot": "669fa49f294b80951be7fd8dcb0f47cfa19760cf"},
    }) + "\n"

    assert opencode_client._extract_opencode_text(stdout) == stdout


def test_usage_and_cost_parse_real_step_finish_shape():
    envelope = {
        "type": "step_finish",
        "sessionID": "ses_1",
        "part": {
            "id": "prt_1", "type": "step-finish", "reason": "stop",
            "tokens": {"total": 40370, "input": 40337, "output": 15,
                       "reasoning": 18, "cache": {"write": 0, "read": 0}},
            "cost": 0.0064316,
        },
    }

    assert opencode_client._usage_from_envelope(envelope) == (40337, 15, 40370)
    assert opencode_client._cost_from_envelope(envelope) == 0.0064316
