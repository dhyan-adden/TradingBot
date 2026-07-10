import json
import subprocess
from pathlib import Path

import pytest

from tradeloop.lib.llm import claude_client as cc_mod
from tradeloop.lib.llm.claude_client import ClaudeStageClient
from tradeloop.lib.llm.client import LLMValidationError
from tradeloop.lib.llm.schemas import Shortlist

FIX = Path(__file__).parent / "fixtures"


def _valid_shortlist_text():
    # reuse the OpenRouter fixture's inner content: a real Shortlist JSON string
    body = json.loads((FIX / "or_ok_shortlist.json").read_text())
    return body["choices"][0]["message"]["content"]


def _envelope(result_text, session_id="sess-1", in_tok=10, out_tok=20,
              model_id="claude-sonnet-4-5"):
    return json.dumps({
        "type": "result", "subtype": "success", "result": result_text,
        "session_id": session_id,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
        "modelUsage": {model_id: {"inputTokens": in_tok, "outputTokens": out_tok}},
    })


def _completed(stdout, code=0, stderr=""):
    return subprocess.CompletedProcess(args=["claude"], returncode=code,
                                       stdout=stdout, stderr=stderr)


def _client(tmp_path, monkeypatch, results):
    """results: list of CompletedProcess or Exception, played in sequence."""
    calls = {"n": 0, "inputs": [], "argv": None, "env": None}

    def fake_run(argv, input=None, capture_output=None, text=None, timeout=None, env=None):
        calls["argv"] = argv
        calls["env"] = env
        calls["inputs"].append(input)
        idx = calls["n"]
        calls["n"] += 1
        item = results[min(idx, len(results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(cc_mod.subprocess, "run", fake_run)
    c = ClaudeStageClient(audit_path=tmp_path / "llm_calls.jsonl", max_retries=3)
    return c, calls


def _last_record(tmp_path):
    return json.loads((tmp_path / "llm_calls.jsonl").read_text().splitlines()[-1])


def test_valid_json_returns_model_and_records_provenance(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope(_valid_shortlist_text()))])
    out = c.call_json("14_shortlist", "system", "user", Shortlist, model="sonnet")
    assert isinstance(out, Shortlist)
    rec = _last_record(tmp_path)
    assert rec["model"] == "claude:sonnet"
    assert rec["model_version"] == "claude-sonnet-4-5"     # from modelUsage
    assert rec["response_id"] == "sess-1"                  # from session_id
    assert rec["prompt_tokens"] == 10 and rec["completion_tokens"] == 20
    assert rec["total_tokens"] == 30 and rec["used_model"] is True


def test_fenced_json_is_extracted(tmp_path, monkeypatch):
    fenced = "```json\n" + _valid_shortlist_text() + "\n```"
    c, _ = _client(tmp_path, monkeypatch, [_completed(_envelope(fenced))])
    assert isinstance(c.call_json("14_shortlist", "s", "u", Shortlist), Shortlist)


def test_prose_wrapped_json_is_extracted(tmp_path, monkeypatch):
    prose = "Here you go:\n" + _valid_shortlist_text() + "\nDone."
    c, _ = _client(tmp_path, monkeypatch, [_completed(_envelope(prose))])
    assert isinstance(c.call_json("14_shortlist", "s", "u", Shortlist), Shortlist)


def test_hollow_object_is_rejected_then_recovers(tmp_path, monkeypatch):
    ok = _completed(_envelope(_valid_shortlist_text()))
    c, calls = _client(tmp_path, monkeypatch,
                       [_completed(_envelope("{}")), _completed(_envelope("{}")), ok])
    out = c.call_json("22_debate", "s", "u", Shortlist, model="opus")
    assert isinstance(out, Shortlist)
    assert calls["n"] == 3                                  # 2 hollow rejected, 3rd good


def test_empty_result_retries_then_raises(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope(""))])
    with pytest.raises(LLMValidationError):
        c.call_json("10_news", "s", "u", Shortlist, model="sonnet")
    assert calls["n"] == 3                                  # max_retries exhausted


def test_unparseable_output_retries_then_raises(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope("not json at all"))])
    with pytest.raises(LLMValidationError):
        c.call_json("10_news", "s", "u", Shortlist, model="sonnet")
    assert calls["n"] == 3


def test_bad_then_good_recovers(tmp_path, monkeypatch):
    ok = _completed(_envelope(_valid_shortlist_text()))
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope("nope")), ok])
    assert isinstance(c.call_json("10_news", "s", "u", Shortlist, model="sonnet"), Shortlist)
    assert calls["n"] == 2


def test_nonzero_exit_retries_then_raises(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch,
                       [_completed("", code=1, stderr="not logged in")])
    with pytest.raises(LLMValidationError):
        c.call_json("10_news", "s", "u", Shortlist, model="sonnet")
    assert calls["n"] == 3


def test_timeout_retries_then_raises(tmp_path, monkeypatch):
    c, calls = _client(tmp_path, monkeypatch,
                       [subprocess.TimeoutExpired(cmd="claude", timeout=120)])
    with pytest.raises(LLMValidationError):
        c.call_json("10_news", "s", "u", Shortlist, model="sonnet")
    assert calls["n"] == 3


def test_prompt_delivered_on_stdin_not_argv(tmp_path, monkeypatch):
    big_user = "SETUP\n" * 5000                              # large uncapped-style block
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope(_valid_shortlist_text()))])
    c.call_json("13_technical", "SYS", big_user, Shortlist, model="sonnet")
    assert big_user in calls["inputs"][0]                    # prompt went to stdin
    assert big_user not in " ".join(calls["argv"])           # NOT in argv (no ARG_MAX)
    assert "--model" in calls["argv"] and "sonnet" in calls["argv"]


def test_forces_toolless_single_shot(tmp_path, monkeypatch):
    # Regression: claude -p is agentic and offers Bash/WebSearch; a stage that
    # calls one dies on --max-turns (error_max_turns). Lock in the no-tools guards.
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope(_valid_shortlist_text()))])
    c.call_json("12_fundamentals", "s", "u", Shortlist, model="sonnet")
    assert "--strict-mcp-config" in calls["argv"]            # no project MCP
    assert "--disallowedTools" in calls["argv"]              # tool execution denied
    assert "Bash" in calls["argv"]                           # incl. the Bash tool
    assert "no tools" in calls["inputs"][0].lower()          # instruction on stdin


def test_subprocess_env_scrubs_anthropic_api_key(tmp_path, monkeypatch):
    # Airtight subscription guarantee: even if an API key is in the parent env,
    # the claude -p subprocess must NOT see it, so it can only use the sub.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
    c, calls = _client(tmp_path, monkeypatch, [_completed(_envelope(_valid_shortlist_text()))])
    c.call_json("10_news", "s", "u", Shortlist, model="sonnet")
    assert "ANTHROPIC_API_KEY" not in (calls["env"] or {})   # forced onto the subscription
    assert "PATH" in (calls["env"] or {})                    # but the rest of the env survives
