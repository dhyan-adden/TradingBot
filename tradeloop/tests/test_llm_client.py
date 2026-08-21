import json
from pathlib import Path

import httpx
import pytest

from tradeloop.lib.llm import client as client_mod
from tradeloop.lib.llm.client import LLMClient
from tradeloop.lib.llm.schemas import Shortlist

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def _client(tmp_path, monkeypatch, responses):
    """Build an LLMClient whose httpx.post is a scripted sequence."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-secret")
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        idx = calls["n"]
        calls["n"] += 1
        item = responses[min(idx, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json=item, request=httpx.Request("POST", url))

    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl", max_retries=3, backoff_base=0.0)
    return c, calls


def test_falls_back_to_reliable_model_when_primary_returns_empty(tmp_path, monkeypatch):
    # regression: deepseek-v4-flash returned empty content, exhausted retries, and
    # killed the whole cycle (false "hold"). Now the assigned model failing should
    # fall back to a reliable model instead of raising.
    empty = {"choices": [{"message": {"content": ""}}]}
    ok = _load("or_ok_shortlist.json")
    c, calls = _client(tmp_path, monkeypatch, [empty, empty, empty, ok])
    out = c.call_json("13_technical", "system", "user", Shortlist,
                      model="deepseek/deepseek-v4-flash")
    assert isinstance(out, Shortlist)                 # recovered - did not raise
    assert calls["n"] == 4                            # 3 flaky primary + 1 fallback
    rec = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert rec["model"] == "minimax/minimax-m3"       # first distinct fallback in the chain
    assert rec["used_model"] is True


def test_fallback_is_distinct_even_when_primary_equals_default(tmp_path, monkeypatch):
    # regression: when a stage's model IS the default (mimo), the fallback must still
    # be a genuinely different model (minimax), not a no-op that leaves it unprotected.
    empty = {"choices": [{"message": {"content": ""}}]}
    ok = _load("or_ok_shortlist.json")
    c, calls = _client(tmp_path, monkeypatch, [empty, empty, empty, ok])
    out = c.call_json("14_shortlist", "system", "user", Shortlist,
                      model="xiaomi/mimo-v2.5")
    assert isinstance(out, Shortlist)                 # recovered despite mimo failing
    rec = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert rec["model"] == "minimax/minimax-m3"       # fell to a DIFFERENT model


def test_hollow_empty_object_rejected_and_falls_back(tmp_path, monkeypatch):
    # regression (live 2026-07-07): minimax-m3 returned a literal {} for
    # 22_debate and 30_trade_plan. {} is valid JSON and validates against the
    # all-defaults schemas, so it bypassed retry AND fallback and cascaded into
    # a silent fake "hold" (orders=0). A hollow {} must be treated as invalid
    # so the existing retry/fallback chain engages.
    hollow = {"choices": [{"message": {"content": "{}"}}]}
    ok = _load("or_ok_shortlist.json")
    c, calls = _client(tmp_path, monkeypatch, [hollow, hollow, hollow, ok])
    out = c.call_json("22_debate", "system", "user", Shortlist,
                      model="minimax/minimax-m3")
    assert isinstance(out, Shortlist)
    assert out.candidates                             # real content, not defaults
    assert calls["n"] == 4                            # 3 hollow primary + 1 fallback
    rec = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert rec["model"] == "xiaomi/mimo-v2.5"         # fell to a DIFFERENT model


def test_call_json_validates_and_records_provenance(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_load("or_ok_shortlist.json")])
    out = c.call_json("14_shortlist", "system", "user", Shortlist)
    assert isinstance(out, Shortlist)
    assert out.candidates[0].ticker == "RELIANCE"
    rec = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert rec["response_id"] == "gen-abc123"
    assert rec["model_version"] == "anthropic/claude-sonnet-4.5"
    assert rec["prompt_tokens"] == 120 and rec["total_tokens"] == 180
    assert rec["prompt"].endswith("user") and "system" in rec["prompt"]
    assert rec["used_model"] is True


def test_call_json_records_provider_reported_openrouter_cost(tmp_path, monkeypatch):
    response = _load("or_ok_shortlist.json")
    response["usage"] = {
        "prompt_tokens": 120,
        "completion_tokens": 60,
        "total_tokens": 180,
        "cost": 0.001234,
    }
    c, _ = _client(tmp_path, monkeypatch, [response])
    c.call_json("14_shortlist", "system", "user", Shortlist)
    rec = json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])
    assert rec["cost_usd"] == 0.001234
    assert rec["cost_known"] is True


def test_call_json_injects_schema_field_names(tmp_path, monkeypatch):
    # Regression guard for the hollow-output bug: the model must SEE the schema
    # field names, else it invents prose keys and pydantic (extra="ignore")
    # returns an all-defaults empty object that "validates" but carries nothing.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-secret")
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["system"] = json["messages"][0]["content"]
        return httpx.Response(200, json=_load("or_ok_shortlist.json"),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl", backoff_base=0.0)
    c.call_json("14_shortlist", "system", "user", Shortlist)
    for field in ("candidates", "composite_score", "evidence"):
        assert field in seen["system"], f"schema field {field!r} not shown to model"


def test_retries_on_transport_error_then_succeeds(tmp_path, monkeypatch):
    err = httpx.ConnectError("boom")
    c, calls = _client(tmp_path, monkeypatch, [err, _load("or_ok_shortlist.json")])
    out = c.call_json("14_shortlist", "s", "u", Shortlist)
    assert isinstance(out, Shortlist)
    assert calls["n"] == 2  # one failure, one success


def test_invalid_json_retried_then_raises(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_load("or_bad_json.json")])
    with pytest.raises(client_mod.LLMValidationError):
        c.call_json("14_shortlist", "s", "u", Shortlist)
    # mimo primary + minimax fallback, max_retries each -> only raises once BOTH exhaust
    assert calls["n"] == 6


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl")
    with pytest.raises(client_mod.LLMConfigError):
        c.call_json("14_shortlist", "s", "u", Shortlist)


def test_reasoning_disabled_in_payload(tmp_path, monkeypatch):
    # regression (live 2026-07-08): mimo/minimax/deepseek are reasoning models and
    # OpenRouter counts hidden reasoning against max_tokens (4000). On complex
    # stages reasoning alone overran the budget -> finish_reason=length with
    # content="" ("model returned empty content") on EVERY retry and fallback,
    # killing the cycle deterministically. All stages are schema-validated JSON
    # extraction, so reasoning burn buys nothing: it must be disabled per-request.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-secret")
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = dict(json)
        return httpx.Response(200, json=_load("or_ok_shortlist.json"),
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl", backoff_base=0.0)
    c.call_json("14_shortlist", "s", "u", Shortlist)
    assert seen["payload"]["reasoning"] == {"enabled": False}


def test_downgrades_response_format_on_400(tmp_path, monkeypatch):
    # A provider that 400s on response_format must not fail the cycle: the client
    # drops response_format and retries on prompt + extraction alone.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-secret")
    payloads = []
    statuses = [400, 200]
    calls = {"n": 0}
    ok = _load("or_ok_shortlist.json")

    def fake_post(url, headers=None, json=None, timeout=None):
        payloads.append(dict(json))  # snapshot: payload is mutated in place on downgrade
        status = statuses[min(calls["n"], len(statuses) - 1)]
        calls["n"] += 1
        body = ok if status == 200 else {"error": {"message": "response_format unsupported"}}
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl", max_retries=3, backoff_base=0.0)
    out = c.call_json("14_shortlist", "s", "u", Shortlist)
    assert isinstance(out, Shortlist)
    assert calls["n"] == 2                          # 400, then success
    assert "response_format" in payloads[0]         # first attempt nudged
    assert "response_format" not in payloads[1]     # retry downgraded after the 400
    assert "reasoning" in payloads[0]               # reasoning-off nudge sent first
    assert "reasoning" not in payloads[1]           # dropped with the same downgrade
