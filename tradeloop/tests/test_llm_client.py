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
    assert calls["n"] == 3  # exhausted max_retries on invalid output


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    c = LLMClient(audit_path=tmp_path / "llm_calls.jsonl")
    with pytest.raises(client_mod.LLMConfigError):
        c.call_json("14_shortlist", "s", "u", Shortlist)
