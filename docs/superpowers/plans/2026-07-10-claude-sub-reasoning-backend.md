# Claude-Sub Reasoning Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every DAG reasoning stage on the Claude subscription via one local `claude -p` call per stage, keeping the deterministic Python driver that owns order, sizing, gates, and provenance, and lift the 150-setup cap so the full scan reaches the screening analysts.

**Architecture:** Extract the trusted DAG loop into a client-agnostic `_run_reasoning_dag(...)`; both backends feed it a client that satisfies the existing `SupportsCallJson` protocol. The OpenRouter path keeps `LLMClient` (dormant fallback); the claude path gets a new `ClaudeStageClient` that shells `claude -p --model <tier> --output-format json --max-turns 1`, delivering the prompt on stdin and reusing the existing brace-extraction, hollow-`{}` rejection, pydantic validation, and `CallRecord` provenance. The flaky LLM-master-dispatch shell path is deleted.

**Tech Stack:** Python 3.11 (conda env `tradingbot`), pydantic v2, pytest, the `claude` CLI (2.1.205), bash cron.

## Global Constraints

- Run all Python under the conda env `tradingbot`: `PATH=/Users/dhyanpatel/anaconda3/envs/tradingbot/bin:$PATH` (the repo requires >=3.11; the `.venv` is 3.9 and will fail collection).
- Never use the em dash; use a plain dash.
- Commit messages: do NOT auto-add any agent name as co-author.
- The claude backend reaches Claude only through the local `claude -p` CLI on the subscription; no Anthropic API, no metered usage.
- `claude -p` reads the prompt from stdin (verified: no positional arg), and its `--output-format json` envelope carries `result`, `session_id`, `usage.{input_tokens,output_tokens}`, and `modelUsage` (verified on CLI 2.1.205). `result` arrives fenced in a ```json block, so JSON is recovered by brace extraction, never a raw `json.loads`.
- Work on branch `feat/claude-sub-reasoning-backend` (already created; the spec is committed there).
- Run the full suite with `pytest -q` from the repo root before the final task; every task keeps the suite green.

---

## File Structure

- `tradeloop/lib/llm/routing.py` (modify) - add the Claude per-stage tier table.
- `tradeloop/lib/llm/client.py` (modify) - extract the shared schema-pinned system prompt; make `LLMClient` self-route by role.
- `tradeloop/lib/llm/stages.py` (modify) - `run_stage` lets the client self-route (drops the explicit OpenRouter model).
- `tradeloop/lib/llm/claude_client.py` (create) - the `ClaudeStageClient` transport.
- `tradeloop/orchestrator.py` (modify) - extract `_run_reasoning_dag`, wire the claude client, delete the shell path.
- `tradeloop/lib/data/ingest.py` (modify) + `tradeloop/config/settings.yaml` (modify) - lift the setup cap.
- `tradeloop/scripts/verify_setup.py` (modify) - preflight claude-auth check.
- `tradeloop/scripts/cron_dispatch.sh` (modify) + `tradeloop/scripts/run_cycle.sh` (modify) - flip cron to claude, delete the dead claude branch.
- Tests: `tradeloop/tests/test_claude_client.py` (create), `tradeloop/tests/test_llm_routing.py`, `tradeloop/tests/test_reasoning_wiring.py`, `tradeloop/tests/data/test_ingest_universe.py`, `tradeloop/tests/test_verify_setup_claude.py` (create).

---

## Task 1: Claude per-stage tier table (routing.py)

**Files:**
- Modify: `tradeloop/lib/llm/routing.py`
- Test: `tradeloop/tests/test_llm_routing.py`

**Interfaces:**
- Produces: `CLAUDE_STAGE_MODELS: dict[str, str]`, `CLAUDE_DEFAULT_MODEL: str = "sonnet"`, `claude_model_for(stage: str) -> str` returning `"haiku" | "sonnet" | "opus"`.

- [ ] **Step 1: Write the failing test**

Append to `tradeloop/tests/test_llm_routing.py`:

```python
from tradeloop.lib.llm import routing


def test_claude_model_for_matches_tiering():
    assert routing.claude_model_for("11_sentiment") == "haiku"
    assert routing.claude_model_for("05_adhoc_intake") == "haiku"
    assert routing.claude_model_for("10_news") == "sonnet"
    assert routing.claude_model_for("50_post_trade") == "sonnet"
    assert routing.claude_model_for("22_debate") == "opus"
    assert routing.claude_model_for("30_trade_plan") == "opus"
    assert routing.claude_model_for("40_risk_report") == "opus"
    assert routing.claude_model_for("41_pm_decision") == "opus"


def test_claude_model_for_defaults_to_sonnet_for_unknown_stage():
    assert routing.claude_model_for("99_unknown") == "sonnet"


def test_every_openrouter_stage_has_a_claude_tier():
    for stage in routing.STAGE_MODELS:
        assert stage in routing.CLAUDE_STAGE_MODELS, f"{stage} missing a claude tier"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tradeloop/tests/test_llm_routing.py::test_claude_model_for_matches_tiering -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'claude_model_for'`

- [ ] **Step 3: Add the table and lookup**

Append to `tradeloop/lib/llm/routing.py`:

```python
# Claude-subscription tiers per stage (used by ClaudeStageClient). haiku =
# lightest classification, sonnet = research/analysis, opus = high-stakes
# decisions. Mirrors the intent of STAGE_MODELS but with native Claude models.
CLAUDE_STAGE_MODELS: dict[str, str] = {
    "05_adhoc_intake": "haiku",
    "10_news": "sonnet",
    "11_sentiment": "haiku",
    "12_fundamentals": "sonnet",
    "13_technical": "sonnet",
    "14_shortlist": "sonnet",
    "20_bull": "sonnet",
    "21_bear": "sonnet",
    "22_debate": "opus",
    "30_trade_plan": "opus",
    "40_risk_report": "opus",
    "41_pm_decision": "opus",
    "50_post_trade": "sonnet",
}

CLAUDE_DEFAULT_MODEL = "sonnet"


def claude_model_for(stage: str) -> str:
    return CLAUDE_STAGE_MODELS.get(stage, CLAUDE_DEFAULT_MODEL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tradeloop/tests/test_llm_routing.py -v`
Expected: PASS (all, including the three new ones)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/llm/routing.py tradeloop/tests/test_llm_routing.py
git commit -m "feat(routing): Claude per-stage tier table (haiku/sonnet/opus)"
```

---

## Task 2: Shared system prompt + client self-routing (client.py, stages.py)

Extract the schema-pinned system prompt so both transports pin field names identically, and make each client resolve its own per-stage model from the role, so `run_stage` stays backend-agnostic.

**Files:**
- Modify: `tradeloop/lib/llm/client.py`
- Modify: `tradeloop/lib/llm/stages.py`
- Test: `tradeloop/tests/test_llm_client.py` (existing tests must stay green)

**Interfaces:**
- Consumes: `routing.model_for` (Task 0, pre-existing).
- Produces: `build_system_content(system: str, schema: type[BaseModel]) -> str` in `client.py`; `LLMClient.call_json` self-routes via `routing.model_for(role)` when `model is None`; `run_stage(name, run_dir, client)` calls `client.call_json(name, system, user, schema)` with no explicit model.

- [ ] **Step 1: Confirm the existing client tests are green first**

Run: `pytest tradeloop/tests/test_llm_client.py -q`
Expected: PASS (baseline before refactor)

- [ ] **Step 2: Extract `build_system_content` and self-route in client.py**

In `tradeloop/lib/llm/client.py`, add the import near the top (after the existing imports):

```python
from tradeloop.lib.llm import routing
```

Add this module-level function above the `LLMClient` class:

```python
def build_system_content(system: str, schema: type[BaseModel]) -> str:
    """Schema-pinned system prompt shared by every stage transport.

    Without the exact JSON Schema the model invents prose keys that never match
    the pydantic fields, so extra='ignore' silently defaults every field and the
    object comes back hollow. Shared by LLMClient (OpenRouter) and
    ClaudeStageClient (subscription) so both pin field names identically.
    """
    schema_hint = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    return (
        f"{system}\n\n"
        "You are one bounded agent inside an Indian-market paper trading "
        "system. India cash equities only, long-only. Return ONE compact JSON "
        "object and nothing else, conforming to this JSON Schema - use these "
        "EXACT field names (not prose labels), correct types, and every required "
        f"field:\n{schema_hint}\n"
        "When a claim rests on a news item, cite it by copying the bracketed "
        "[news_id] tokens from the input verbatim into the nearest 'evidence' "
        "array. Do not request order execution; risk, gate and broker controls "
        "are deterministic and final."
    )
```

In `LLMClient.call_json`, change the model default line from:

```python
        model = model or self.default_model
```

to:

```python
        model = model or routing.model_for(role)
```

And replace the inline `schema_hint = ...` + `system_content = (...)` block (the two statements that build `schema_hint` and `system_content`) with the single line:

```python
        system_content = build_system_content(system, schema)
```

(Leave `prompt = f"{system}\n\n{user}"` unchanged.)

- [ ] **Step 3: Let run_stage self-route in stages.py**

In `tradeloop/lib/llm/stages.py`, `run_stage`, remove the line `model = routing.model_for(name)` and change the call from:

```python
    result = client.call_json(name, system, user, schema, model)
```

to:

```python
    result = client.call_json(name, system, user, schema)
```

Then, if `routing` is now unused in `stages.py`, remove its import `from tradeloop.lib.llm import routing`.

- [ ] **Step 4: Run the client and DAG-wiring tests**

Run: `pytest tradeloop/tests/test_llm_client.py tradeloop/tests/test_reasoning_wiring.py::test_openrouter_backend_runs_dag_and_python_writes_orders_json -q`
Expected: PASS (the refactor is behavior-preserving: `14_shortlist` resolves to `xiaomi/mimo-v2.5`, the old default)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/llm/client.py tradeloop/lib/llm/stages.py
git commit -m "refactor(llm): share schema-pinned prompt, self-route model by role"
```

---

## Task 3: ClaudeStageClient transport (claude_client.py)

The one new component with a bounded failure surface, covered exhaustively.

**Files:**
- Create: `tradeloop/lib/llm/claude_client.py`
- Test: `tradeloop/tests/test_claude_client.py`

**Interfaces:**
- Consumes: `build_system_content`, `CallRecord`, `LLMValidationError`, `_failed_record`, `_parse_json_object` (from `client.py`); `routing.claude_model_for` (Task 1).
- Produces: `ClaudeStageClient(audit_path, cli="claude", max_retries=3, per_call_timeout=120.0)` with `call_json(role, system, user, schema, model=None) -> BaseModel`, satisfying `SupportsCallJson`.

- [ ] **Step 1: Write the failing tests (exhaustive)**

Create `tradeloop/tests/test_claude_client.py`:

```python
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
    calls = {"n": 0, "inputs": [], "argv": None}

    def fake_run(argv, input=None, capture_output=None, text=None, timeout=None):
        calls["argv"] = argv
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tradeloop/tests/test_claude_client.py -q`
Expected: FAIL with `ModuleNotFoundError: tradeloop.lib.llm.claude_client`

- [ ] **Step 3: Implement ClaudeStageClient**

Create `tradeloop/lib/llm/claude_client.py`:

```python
"""Claude-subscription stage transport: one `claude -p` per DAG stage.

Mirrors LLMClient's SupportsCallJson contract but reaches Claude models on the
local subscription through the `claude` CLI instead of OpenRouter over httpx.
The prompt is delivered on stdin (no ARG_MAX ceiling for large setup blocks),
and output handling reuses client.py's schema-pinned system prompt, brace
extraction, hollow-{} rejection, pydantic validation, and CallRecord provenance
so the audit log is byte-compatible with the OpenRouter path.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel, ValidationError

from tradeloop.lib.llm import routing
from tradeloop.lib.llm.client import (
    CallRecord, LLMValidationError, _failed_record, _parse_json_object,
    build_system_content,
)


class ClaudeStageClient:
    def __init__(self, audit_path: Path, cli: str = "claude",
                 max_retries: int = 3, per_call_timeout: float = 120.0) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.cli = cli
        self.max_retries = max_retries
        self.per_call_timeout = per_call_timeout

    def call_json(self, role: str, system: str, user: str,
                  schema: type[BaseModel], model: str | None = None) -> BaseModel:
        model = model or routing.claude_model_for(role)
        system_content = build_system_content(system, schema)
        stdin_prompt = f"{system_content}\n\n{user}"   # to claude on stdin; no ARG_MAX
        prompt = f"{system}\n\n{user}"                 # recorded for provenance parity
        argv = [self.cli, "-p", "--model", model,
                "--output-format", "json", "--max-turns", "1"]

        last_exc: Exception | None = None
        for _ in range(self.max_retries):
            try:
                proc = subprocess.run(argv, input=stdin_prompt, capture_output=True,
                                      text=True, timeout=self.per_call_timeout)
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"claude -p exit {proc.returncode}: {(proc.stderr or '')[:200]}")
                envelope = json.loads(proc.stdout)
                text = str(envelope.get("result", ""))
                obj = _parse_json_object(text)         # fence strip + brace extract + reject {}
                validated = schema.model_validate(obj)
            except (subprocess.TimeoutExpired, subprocess.SubprocessError,
                    RuntimeError, ValueError, ValidationError) as exc:
                last_exc = exc
                self._record(_failed_record(role, f"claude:{model}", prompt, str(exc)))
                continue
            usage = envelope.get("usage", {}) or {}
            in_tok = int(usage.get("input_tokens", 0))
            out_tok = int(usage.get("output_tokens", 0))
            self._record(CallRecord(
                role=role, model=f"claude:{model}",
                model_version=str(next(iter(envelope.get("modelUsage", {})), model)),
                response_id=str(envelope.get("session_id", "")),
                prompt=prompt, response=text,
                prompt_tokens=in_tok, completion_tokens=out_tok,
                total_tokens=in_tok + out_tok, used_model=True))
            return validated
        raise LLMValidationError(
            f"{role} failed on claude:{model} after {self.max_retries} tries: {last_exc}")

    def _record(self, record: CallRecord) -> None:
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record)) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tradeloop/tests/test_claude_client.py -q`
Expected: PASS (all 11)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/lib/llm/claude_client.py tradeloop/tests/test_claude_client.py
git commit -m "feat(llm): ClaudeStageClient - one claude -p per stage on the sub"
```

---

## Task 4: Wire the claude backend into the DAG, delete the shell path (orchestrator.py)

**Files:**
- Modify: `tradeloop/orchestrator.py`
- Test: `tradeloop/tests/test_reasoning_wiring.py`, `tradeloop/tests/test_cycle_guards.py`

**Interfaces:**
- Consumes: `ClaudeStageClient` (Task 3), `LLMClient`.
- Produces: `_run_reasoning(run_dir, mode, backend, timeout, client=None, settings=None) -> int` (unchanged signature) constructs the backend's client when none is injected; `_run_reasoning_dag(run_dir, mode, timeout, client, settings=None, generated_by="tradeloop.reasoning.p1") -> int`. `_run_reasoning_claude` and `_canonicalize_claude_orders` are removed.

- [ ] **Step 1: Replace the claude wiring tests (they assert the deleted shell path)**

In `tradeloop/tests/test_reasoning_wiring.py`:

Delete these three tests and the `_claude_run_writing` helper entirely: `test_claude_backend_dispatches_to_subagent_subprocess`, `test_claude_hold_is_canonical_dict_not_still_running`, `test_claude_buy_renders_and_does_not_crash_dashboard`.

Add this test (the claude backend now runs the DAG in-process, like openrouter, stamping its provenance):

```python
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
```

(Keep `test_openrouter_backend_runs_dag_and_python_writes_orders_json`, `test_postclose_skips_trade_stages_and_proposes_nothing`, and `test_unknown_backend_raises`.)

- [ ] **Step 2: Run to verify the new test fails**

Run: `pytest tradeloop/tests/test_reasoning_wiring.py::test_claude_backend_runs_dag_in_process -q`
Expected: FAIL (claude backend still shells out; `generated_by` is not stamped by the DAG, and orders.json is not written in-process)

- [ ] **Step 3: Refactor orchestrator.py**

At the top of `tradeloop/orchestrator.py`, add:

```python
from tradeloop.lib.llm.claude_client import ClaudeStageClient
```

Remove `import subprocess` (no longer used after the shell path is deleted).

Delete the functions `_canonicalize_claude_orders` and `_run_reasoning_claude` entirely.

Replace the body of `_run_reasoning` with:

```python
def _run_reasoning(run_dir, mode, backend, timeout, client=None, settings=None) -> int:
    """Dispatch reasoning to the selected backend's client, then run the one
    deterministic DAG. Both backends write a schema-valid orders.json; the route
    phase validates + gates it identically, so risk controls are backend-independent.

    - "openrouter" -> LLMClient (httpx -> OpenRouter): dormant fallback.
    - "claude"     -> ClaudeStageClient (claude -p per stage on your subscription).
    """
    backend = (backend or "openrouter").lower()
    if backend not in ("openrouter", "claude"):
        raise ValueError(f"unknown reasoning backend {backend!r} (use claude|openrouter)")
    if client is None:
        client = (ClaudeStageClient(audit_path=run_dir / "llm_calls.jsonl")
                  if backend == "claude"
                  else LLMClient(audit_path=run_dir / "llm_calls.jsonl"))
    generated_by = ("tradeloop.reasoning.claude" if backend == "claude"
                    else "tradeloop.reasoning.p1")
    return _run_reasoning_dag(run_dir, mode, timeout, client, settings, generated_by)
```

Rename `_run_reasoning_openrouter` to `_run_reasoning_dag` and change its signature and the client-construction + generated_by lines. The full function becomes:

```python
def _run_reasoning_dag(run_dir, mode, timeout, client, settings=None,
                       generated_by="tradeloop.reasoning.p1") -> int:
    """Deterministic DAG: each stage returns a validated pydantic form written to
    run_dir/<stage>.json; Python - not the LLM - serialises orders.json from the
    validated PMDecision. Client-agnostic: OpenRouter or Claude behind the same loop."""
    deadline = time.monotonic() + timeout  # bound the DAG exactly as P0's timeout did

    dag = list(stages.DAG)
    if mode == "adhoc" and (run_dir / "user_request.md").exists():
        if time.monotonic() > deadline:
            return -1
        intake = stages.run_stage("05_adhoc_intake", run_dir, client)
        wanted = {s.removesuffix(".md") for s in intake.required_stages}
        if wanted:
            dag = [s for s in dag if s in wanted]
    if mode not in _ORDER_MODES:  # intraday/postclose: no order stages
        dag = [s for s in dag if s not in _TRADE_STAGES]

    for name in dag:
        if time.monotonic() > deadline:
            return -1
        try:
            stages.run_stage(name, run_dir, client)
            if name == "30_trade_plan" and settings is not None:
                _size_trade_plan(run_dir, settings)  # deterministic qty, not the LLM's guess
        except Exception as exc:
            (run_dir / "reasoning_error.txt").write_text(
                f"reasoning failed at {name}: {exc}\n", encoding="utf-8")
            return -2

    if "41_pm_decision" in dag:
        pm = PMDecision.model_validate_json((run_dir / "41_pm_decision.json").read_text())
        orders, held = pm.orders, pm.held
    else:
        orders, held = [], []
    orders_file = {
        "mode": mode,
        "live_orders_enabled": False,
        "generated_by": generated_by,
        "orders": [o.model_dump() for o in orders],
        "held": [o.model_dump() for o in held],
    }
    (run_dir / "orders.json").write_text(json.dumps(orders_file, indent=2), encoding="utf-8")
    return 0
```

- [ ] **Step 4: Run the reasoning + guard tests**

Run: `pytest tradeloop/tests/test_reasoning_wiring.py tradeloop/tests/test_cycle_guards.py -q`
Expected: PASS (new claude test green; the openrouter DAG tests and cycle guards unchanged)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS (confirm no other test referenced the deleted functions)

- [ ] **Step 6: Commit**

```bash
git add tradeloop/orchestrator.py tradeloop/tests/test_reasoning_wiring.py
git commit -m "refactor(orchestrator): claude backend runs the deterministic DAG; drop shell path"
```

---

## Task 5: Lift the setup cap (ingest.py, settings.yaml)

**Files:**
- Modify: `tradeloop/lib/data/ingest.py:88-89,120-123`
- Modify: `tradeloop/config/settings.yaml:41-43`
- Test: `tradeloop/tests/data/test_ingest_universe.py`

**Interfaces:**
- Produces: `ingest.run(..., max_setups_downstream=0)` (or config `null`) writes every scanned setup to `02_setups_raw.md`; a positive integer still truncates.

- [ ] **Step 1: Write the failing tests**

Append to `tradeloop/tests/data/test_ingest_universe.py`:

```python
def test_uncapped_keeps_all_setups_downstream(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    fake = [_setup("AAA", 9.0), _setup("BBB", 8.0), _setup("CCC", 7.0)]
    monkeypatch.setattr(ingest, "scan_universe", lambda *a, **k: list(fake))
    monkeypatch.setattr(ingest, "load_universe", lambda *a, **k: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(ingest, "_collect_news", lambda *a, **k: ([], []))

    snap = ingest.run(datetime(2026, 7, 6, 9, 0), run_dir=run_dir,
                      kite_client=object(), config_dir=Path("tradeloop/config"),
                      max_setups_downstream=0)  # 0 = no cap, analyze the full scan

    assert {s.ticker for s in snap.setups} == {"AAA", "BBB", "CCC"}


def test_cap_larger_than_scan_keeps_all(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    fake = [_setup("AAA", 9.0), _setup("BBB", 8.0)]
    monkeypatch.setattr(ingest, "scan_universe", lambda *a, **k: list(fake))
    monkeypatch.setattr(ingest, "load_universe", lambda *a, **k: ["AAA", "BBB"])
    monkeypatch.setattr(ingest, "_collect_news", lambda *a, **k: ([], []))

    snap = ingest.run(datetime(2026, 7, 6, 9, 0), run_dir=run_dir,
                      kite_client=object(), config_dir=Path("tradeloop/config"),
                      max_setups_downstream=10)

    assert {s.ticker for s in snap.setups} == {"AAA", "BBB"}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tradeloop/tests/data/test_ingest_universe.py::test_uncapped_keeps_all_setups_downstream -q`
Expected: FAIL - with `max_setups_downstream=0`, `setups[:0]` currently returns `[]`, so `snap.setups` is empty

- [ ] **Step 3: Add the uncapped guard in ingest.py**

In `tradeloop/lib/data/ingest.py`, change the `top_n` resolution (currently lines 88-89) to tolerate a `null` config value:

```python
    cfg_cap = uni.get("max_setups_downstream", 25)          # may be None (null) = uncapped
    top_n = max_setups_downstream if max_setups_downstream is not None else cfg_cap
```

Change the truncation line (currently line 123) from:

```python
    setups = setups[:top_n]
```

to:

```python
    if top_n:  # None or 0 -> analyze the full tradeable scan (no pre-truncation)
        setups = setups[:top_n]
```

- [ ] **Step 4: Run the ingest tests to verify pass**

Run: `pytest tradeloop/tests/data/test_ingest_universe.py -q`
Expected: PASS (existing cap-to-2 and overflow-blend tests still pass; the two new ones pass)

- [ ] **Step 5: Set the config to uncapped**

In `tradeloop/config/settings.yaml`, replace lines 41-43 (the `max_setups_downstream: 150` block and its comment) with:

```yaml
  max_setups_downstream: null  # null (or 0) = analyze the FULL tradeable scan; the
                               # aggregate shortlister is the selector over everything.
                               # Full scan still saved to disk. Set a number to re-cap
                               # (required if falling back to the OpenRouter backend,
                               # whose small models cannot take the full block).
```

- [ ] **Step 6: Commit**

```bash
git add tradeloop/lib/data/ingest.py tradeloop/config/settings.yaml tradeloop/tests/data/test_ingest_universe.py
git commit -m "feat(ingest): lift the 150-setup cap so the full scan reaches the analysts"
```

---

## Task 6: Preflight claude-auth check (verify_setup.py)

Fail loudly at prepare if the `claude` CLI is not authenticated, so an expired login never surfaces mid-DAG.

**Files:**
- Modify: `tradeloop/scripts/verify_setup.py`
- Test: `tradeloop/tests/test_verify_setup_claude.py`

**Interfaces:**
- Produces: `claude_authenticated(cli="claude", timeout=15.0) -> bool` in `verify_setup.py`; `verify(mode, check_live_readiness=False, backend=None)` prints `tradeloop_setup=CLAUDE_AUTH_MISSING` and returns 4 when `backend == "claude"` and the CLI is not authenticated.

- [ ] **Step 1: Write the failing test**

Create `tradeloop/tests/test_verify_setup_claude.py`:

```python
import subprocess

from tradeloop.scripts import verify_setup


def test_claude_authenticated_true_on_zero_exit(monkeypatch):
    monkeypatch.setattr(verify_setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="ok", stderr=""))
    assert verify_setup.claude_authenticated() is True


def test_claude_authenticated_false_on_nonzero(monkeypatch):
    monkeypatch.setattr(verify_setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="login"))
    assert verify_setup.claude_authenticated() is False


def test_claude_authenticated_false_on_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=15)
    monkeypatch.setattr(verify_setup.subprocess, "run", boom)
    assert verify_setup.claude_authenticated() is False


def test_verify_blocks_claude_backend_when_unauthenticated(monkeypatch, capsys):
    monkeypatch.setattr(verify_setup, "claude_authenticated", lambda *a, **k: False)
    rc = verify_setup.verify("premarket", backend="claude")
    assert rc == 4
    assert "CLAUDE_AUTH_MISSING" in capsys.readouterr().out


def test_verify_ignores_claude_auth_for_openrouter(monkeypatch, capsys):
    monkeypatch.setattr(verify_setup, "claude_authenticated", lambda *a, **k: False)
    rc = verify_setup.verify("premarket", backend="openrouter")
    assert rc == 0
    assert "tradeloop_setup=OK" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tradeloop/tests/test_verify_setup_claude.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'claude_authenticated'`

- [ ] **Step 3: Implement the check**

In `tradeloop/scripts/verify_setup.py`, add `import subprocess` to the imports, then add:

```python
def claude_authenticated(cli: str = "claude", timeout: float = 15.0) -> bool:
    """True when the claude CLI answers a trivial prompt (a proxy for a live
    subscription login on this machine). Any nonzero exit, error, or timeout
    reads as not-authenticated so the cycle fails loudly at prepare."""
    try:
        proc = subprocess.run(
            [cli, "-p", "--model", "haiku", "--max-turns", "1"],
            input="reply with OK", capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False
```

Change the `verify` signature and add the gate. Replace:

```python
def verify(mode: str, check_live_readiness: bool = False) -> int:
```

with:

```python
def verify(mode: str, check_live_readiness: bool = False, backend: str | None = None) -> int:
```

and immediately before the final `print(f"tradeloop_setup=OK mode={mode}")` line, insert:

```python
    if backend == "claude" and not claude_authenticated():
        print("tradeloop_setup=CLAUDE_AUTH_MISSING")
        return 4
```

In `main`, add the argument and pass it through. After the existing `--health` argument line add:

```python
    parser.add_argument("--backend", default=None, choices=["openrouter", "claude"])
```

and change the final `return verify(args.mode, args.check_live_readiness)` to:

```python
    return verify(args.mode, args.check_live_readiness, backend=args.backend)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tradeloop/tests/test_verify_setup_claude.py -q`
Expected: PASS (all 5)

- [ ] **Step 5: Commit**

```bash
git add tradeloop/scripts/verify_setup.py tradeloop/tests/test_verify_setup_claude.py
git commit -m "feat(verify): preflight claude-auth check for the claude backend"
```

---

## Task 7: Flip cron to claude, delete the dead shell branch (cron_dispatch.sh, run_cycle.sh)

No unit test - this is an ops wiring change, validated by Task 8's E2E. Keep the diff minimal.

**Files:**
- Modify: `tradeloop/scripts/cron_dispatch.sh:20-22`
- Modify: `tradeloop/scripts/run_cycle.sh` (remove the now-unused `claude)` branch)

- [ ] **Step 1: Point the 08:00 cron at the claude backend**

In `tradeloop/scripts/cron_dispatch.sh`, in the `0800)` case, change the exec line from:

```bash
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket
```

to:

```bash
    exec env ZERODHA_ENABLE_DATA=true "$PY" -m tradeloop.orchestrator premarket --backend claude
```

Update the comment above it to read "Proven propose path (in-process Claude DAG, on the subscription)."

- [ ] **Step 2: Delete the dead run_cycle.sh claude branch**

In `tradeloop/scripts/run_cycle.sh`, remove the entire `claude)` case block from the `case "$TRADELOOP_AGENT" in` statement (the `claude)` branch that execs `claude -p ... --allowedTools "Task,..."`). Leave the `codex)` and `*)` branches. The orchestrator no longer shells this path; the claude backend now runs in-process.

- [ ] **Step 3: Sanity-check the scripts still parse**

Run: `bash -n tradeloop/scripts/cron_dispatch.sh && bash -n tradeloop/scripts/run_cycle.sh && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add tradeloop/scripts/cron_dispatch.sh tradeloop/scripts/run_cycle.sh
git commit -m "chore(cron): run the daily premarket cycle on the claude backend"
```

---

## Task 8: E2E validation from the user's output perspective

The primary-weight test per the spec. Not a code change - a real cycle judged by what you would see at the terminal and dashboard. Requires a live Kite auth token for the scan (the daily `npm run auth:zerodha` ritual) and a logged-in `claude` CLI.

**Files:**
- None (validation only). If a defect surfaces, fix it in the owning task's files and re-run.

- [ ] **Step 1: Preflight**

Run: `/Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python tradeloop/scripts/verify_setup.py --mode premarket --backend claude`
Expected: `tradeloop_setup=OK mode=premarket` (if `CLAUDE_AUTH_MISSING`, run `claude` once interactively to log in, or `claude setup-token`, then retry)

- [ ] **Step 2: Run one real premarket cycle on the claude backend**

Run: `ZERODHA_ENABLE_DATA=true /Users/dhyanpatel/anaconda3/envs/tradingbot/bin/python -m tradeloop.orchestrator premarket --backend claude`
Expected terminal line: `tradeloop_cycle=AWAITING_APPROVAL mode=premarket orders=N run_dir=tradeloop/runs/<ts>_premarket`

- [ ] **Step 3: Judge the run from output (acceptance criteria)**

Let `RUN=tradeloop/runs/<ts>_premarket` from Step 2. Verify each:

```bash
# provenance: ONLY claude models, zero OpenRouter
python3 -c "import json; ms={json.loads(l)['model'] for l in open('$RUN/llm_calls.jsonl')}; print('models:', ms); assert all(m.startswith('claude:') for m in ms), 'OpenRouter leak!'"
# orders.json is the Python dict shape, stamped claude
python3 -c "import json; o=json.load(open('$RUN/orders.json')); assert isinstance(o,dict); print('generated_by:', o['generated_by'], 'orders:', len(o['orders']))"
# the FULL scan reached the analysts (not truncated to 150)
echo "full_scan: $(wc -l < $RUN/full_scan.jsonl)  ·  setups_raw setups: $(grep -c . $RUN/02_setups_raw.md)"
```

Then open the dashboard and confirm the run renders truthfully (a real proposal or an honest hold, never a false "still running"). If there are orders, confirm they are correctly sized (quantity is the deterministic size, not a lowballed guess) and price-grounded (entry/stop match the frozen scan).

- [ ] **Step 4: Record the outcome**

Note the run directory, the models used, order count, full-scan size, and the wall-clock duration in the run's carry-forward context. If the cycle exceeded `cycle_timeout_seconds` (1200s), raise it in `settings.yaml` and re-run.

- [ ] **Step 5: Final full suite + commit any fixes**

Run: `pytest -q`
Expected: PASS. Commit any defect fixes to their owning task's files with a descriptive message.

---

## Self-Review

**Spec coverage:**
- Change 1 backend: Tasks 1 (tiering), 2 (shared prompt/self-route), 3 (ClaudeStageClient), 4 (DAG wiring + delete shell path), 7 (cron flip) - covered.
- Change 2 cap: Task 5 - covered.
- Robustness (per-call timeout, stdin, preflight auth, fail-loud, boundary isolation): per-call timeout + stdin in Task 3; preflight auth in Task 6; fail-loud is the reused DAG contract in Task 4; boundary isolation is the injected-client design in Tasks 3-4 - covered.
- Testing (exhaustive units on the two bounded surfaces + E2E from user output): Tasks 3 and 5 (exhaustive units), Task 8 (E2E) - covered.
- Rollback (`--backend openrouter` + re-cap): preserved in Task 4 (openrouter branch intact) and documented in Task 5's config comment - covered.

**Placeholder scan:** none - every code step shows complete code and every command shows expected output.

**Type consistency:** `ClaudeStageClient.call_json(role, system, user, schema, model=None)` matches `SupportsCallJson`; `build_system_content(system, schema)` is defined in Task 2 and consumed in Task 3; `_run_reasoning_dag(run_dir, mode, timeout, client, settings, generated_by)` is defined and called consistently in Task 4; `claude_model_for` defined in Task 1, consumed in Task 3.
